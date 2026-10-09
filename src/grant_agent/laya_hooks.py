"""Small, self-contained hooks that put LAYA's learned decisions in front of the big model.

Three decisions, one question set (tools/laya/question_sets/neyvia.learned.json):
  taste_triage  after the deterministic page checks: repair first, or ask the model critique?
  page_done     browser: is the goal complete (required evidence on the page plus an action receipt)?
  cl_route      Connected Language: does this request belong to the proposed manual layer?

Each answers above the same 0.95 gate only through admitted, labelled outcomes in the service's memory
(exact or abstract match). Everything else is handed up, so a caller always keeps its checked route:
``{"route": "laya" | "escalate" | "unavailable", "decision": value-or-None}``. Every call leaves a receipt in
the LAYA ledger (answered / escalated / unavailable), which the status-strip panel shows.

This module imports nothing from the taste, browser or CL code, so those can call it without a merge conflict.
Call site for the taste loop (one line, after ``page_checks`` runs)::

    from grant_agent.laya_hooks import triage_taste; verdict = triage_taste(root, checks)  # verdict["decision"]
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

SET = "neyvia.learned@2"
GATE = 0.95
SCOPES = {"taste_triage": {"domain": "taste-triage"}, "page_done": {"domain": "CL-State"}, "cl_route": {"domain": "cl-route"}}
TASKS = {"taste_triage": "taste-triage", "page_done": "browser", "cl_route": "cl-route"}
PATHS = {"taste_triage": "laya.taste_triage", "page_done": "browser.page_done", "cl_route": "cl.route_layer"}
CHECKS = ("theme-dark", "side-void", "visible-dash", "stock-phrase", "abstract-art")
VOCAB_FILE = Path(__file__).resolve().parents[2] / "tools" / "laya" / "route_vocab.json"


def laya_ready() -> bool:
    """True when a LAYA service is configured and (for the owned one) ready; no network call."""
    import os
    if os.environ.get("NEYVIA_LAYA_URL"):
        return True
    from .laya_host import current_url
    return current_url() is not None


def _endpoint():
    from .laya_service import endpoint
    return endpoint()


def decide(root, question: str, state: dict, *, timeout_s: float = 8.0, label: str = "", estimate_savings=True) -> dict:
    """Ask one learned question. Never raises; a failure is an `unavailable` receipt."""
    from .laya_ledger import record
    started = time.monotonic()
    chars = len(json.dumps(state, default=str))

    def finish(outcome, result, **extra):
        record(root, task=TASKS[question], path=PATHS[question], decision=label or question, outcome=outcome,
               latency_ms=(time.monotonic() - started) * 1000, confidence=extra.pop("confidence", None),
               prompt_chars=chars, detail=extra.pop("detail", ""), **extra)
        return result

    from .laya_instant import query
    options = ['repair_first', 'ask_critic'] if question == 'taste_triage' else ['false', 'true']
    instant = query(root, 'hook:' + question, state, labels=options)
    if not instant.get('escalate') and instant.get('confidence', 0) >= GATE:
        value = instant['answer'] if question == 'taste_triage' else instant['answer'] == 'true'
        return finish('answered', {'route': 'laya', 'decision': value, 'confidence': instant['confidence'],
            'source': instant['source'], 'confidenceKind': instant.get('confidenceKind')},
            confidence=instant['confidence'], detail=instant.get('confidenceKind', 'laya-instant'),
            **({} if estimate_savings and not (question == 'cl_route' and value is False)
               else {'tokensSavedEstimate': 0}))
    if instant.get('conflict') or instant.get('reason') == 'personal-region-ambiguous':
        return finish('escalated', {'route': 'escalate', 'decision': None, 'reason': 'episode-conflict'})
    try:
        url = _endpoint()
    except ValueError as exc:
        return finish("unavailable", {"route": "unavailable", "decision": None, "reason": str(exc)[:160]}, detail=str(exc)[:160])
    payload = json.dumps({"set": SET, "questions": [question], "state": state, "scope": SCOPES[question], "client": "neyvia-" + question},
                         ensure_ascii=False, sort_keys=True).encode("utf-8")
    try:
        request = urllib.request.Request(url + "/v1/decide", payload, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = json.load(response)
        answer = body["answers"][question]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as exc:
        return finish("unavailable", {"route": "unavailable", "decision": None, "reason": type(exc).__name__}, detail=type(exc).__name__)
    probability = float(answer.get("top_probability") or 0)
    accepted = str(answer.get("policy", "")).startswith("answer") and probability >= GATE and not answer.get("conflict")
    source = str(answer.get("source") or "")
    if accepted:
        value = answer["answer"]
        if question != "taste_triage":
            value = value == "true"
        return finish("answered", {"route": "laya", "decision": value, "confidence": probability, "source": source,
                                   "decisionId": body.get("decision_id"),
                                   "confidenceKind": answer.get("confidence_kind")}, confidence=probability,
                      detail=answer.get("confidence_kind") or source,
                      **({} if estimate_savings and not (question == 'cl_route' and value is False)
                         else {'tokensSavedEstimate': 0}))
    return finish("escalated", {"route": "escalate", "decision": None, "confidence": probability, "source": source,
                                "decisionId": body.get("decision_id"),
                                "reason": "conflict" if answer.get("conflict") else "below-gate"}, confidence=probability,
                  detail="conflict" if answer.get("conflict") else "below-gate:" + source)


def learn_outcome(root, question, state, correct, evidence, *, verdict=None):
    """Admit an independent app receipt locally and to the service; never label a guess."""
    if question not in SCOPES or evidence.get('passed') is not True or not evidence.get('receipt') or \
            evidence.get('verifier') in {None, '', 'laya', 'self', 'user'}:
        return {'learned': False, 'reason': 'independent-verification-required'}
    from .laya_instant import store
    value = str(correct).lower() if isinstance(correct, bool) else correct
    try:
        local = store(str(Path(root).resolve())).learn('hook:' + question, state, value,
            source=str(evidence['receipt']), evidence=evidence)
        from .laya_outcomes import enqueue
        queued = enqueue(root, question, state, value, evidence, (verdict or {}).get('decisionId'))
        from .laya_instant_ingest import watch
        watch(root)
        return {**local, **queued}
    except Exception as exc:
        return {'learned': False, 'reason': type(exc).__name__}



def learn_route(root, task, actual_layer, receipt, *, verdict=None):
    layer = (verdict or {}).get('layer') or candidate_layer(task)
    if not layer:
        return {'learned': False, 'reason': 'no-single-candidate'}
    return learn_outcome(root, 'cl_route', route_state(task, layer), layer == actual_layer,
        {'receipt': receipt, 'verifier': 'cl-successful-dispatch', 'passed': True, 'actualLayer': actual_layer},
        verdict=verdict)


# ---- taste triage -----------------------------------------------------------------------------

def taste_state(checks: dict, page_id: str = "") -> dict:
    """The question's state from `taste_checks.page_checks` output (or an equivalent dict)."""
    by_name = {row["check"]: row for row in checks.get("checks", [])}
    return {"checks": {name: {"passed": bool(by_name[name]["passed"]), "hits": len(by_name[name].get("hits") or [])}
                       for name in CHECKS if name in by_name},
            "blocks": int(checks.get("blocks", 0)), "renderValid": bool(checks.get("renderValid", True)), "pageId": page_id}


def triage_taste(root, checks: dict, page_id: str = "") -> dict:
    """decision: "repair_first" (skip the critique, repair the check hits) | "ask_critic" | None (not confident)."""
    state = taste_state(checks, page_id)
    if set(state["checks"]) != set(CHECKS):
        return {"route": "escalate", "decision": None, "reason": "incomplete-checks"}
    return decide(root, "taste_triage", state, label="repair-or-critic", estimate_savings=False)


# ---- browser page_done ------------------------------------------------------------------------

def page_done_state(goal, page, current, action_receipts, evidence) -> dict:
    receipts = action_receipts if isinstance(action_receipts, list) else []
    summary = "; ".join(str((row.get("summary") or row.get("status") or row.get("action") or row) if isinstance(row, dict) else row)[:80]
                        for row in receipts if row)[:300]
    return {"goal": goal, "page": page, "current": current, "action_receipts": receipts,
            "evidence": evidence if isinstance(evidence, str) else "", "receipt_summary": summary}


# ---- Connected Language routing ---------------------------------------------------------------

_STOP = set("a an and are as at be by do does for from has have how i in into is it its of on or that the this to up use was what when where which with you your can not no new all any each per via also then than their them they these those will would should may might must".split())
_vocab_cache = None


def tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z0-9]{2,}", str(text).lower()) if t not in _STOP}


def load_vocab() -> dict:
    global _vocab_cache
    if _vocab_cache is None:
        try:
            _vocab_cache = json.loads(VOCAB_FILE.read_text(encoding="utf-8"))["layers"]
        except (OSError, ValueError, KeyError):
            _vocab_cache = {}
    return _vocab_cache


def route_state(task: str, layer: str, vocab: dict | None = None) -> dict:
    vocab = load_vocab() if vocab is None else vocab
    words = tokens(task)
    mine = sorted(words & set(vocab.get(layer, [])))
    rivals = sorted(f"{other}:{w}" for other, terms in vocab.items() if other != layer for w in sorted(words & set(terms)))
    count = len(mine)
    return {"task": task[:2000], "layer": layer, "layer_hit": ",".join(mine), "layer_hit_count": str(count) if count < 4 else "4+",
            "rival_hit": ",".join(rivals[:6])}


def candidate_layer(task: str, vocab: dict | None = None):
    """The layer whose vocabulary matches the request best; None when nothing matches or two tie."""
    vocab = load_vocab() if vocab is None else vocab
    words = tokens(task)
    scores = sorted(((len(words & set(terms)), layer) for layer, terms in vocab.items()), reverse=True)
    if not scores or scores[0][0] == 0 or (len(scores) > 1 and scores[1][0] == scores[0][0]):
        return None
    return scores[0][1]


def route_layer(root, task: str) -> dict:
    """decision: the layer name when LAYA confirms the best candidate, else None (the model routes)."""
    vocab = load_vocab()
    layer = candidate_layer(task, vocab)
    if not layer:
        return {"route": "escalate", "decision": None, "reason": "no-single-candidate"}
    verdict = decide(root, "cl_route", route_state(task, layer, vocab), label="route:" + layer)
    if verdict["route"] == "laya":
        return {**verdict, "decision": layer if verdict["decision"] else None, "layer": layer,
                **({} if verdict["decision"] else {"route": "escalate", "reason": "laya-says-no"})}
    return {**verdict, "layer": layer}


# ---- one call for any harness loop ------------------------------------------------------------

def verify(question: str, candidate, evidence: dict, *, root=None, timeout_s: float = 8.0) -> dict:
    """A fast, cheap check for a model that is unsure of its own output.

    ``question``   "taste_triage" | "page_done" | "cl_route"
    ``candidate``  the answer the caller proposes (taste: "repair_first"/"ask_critic"; page_done: bool;
                   cl_route: the layer name)
    ``evidence``   taste_triage: the `taste_checks.page_checks` dict; page_done: {goal, page, current,
                   action_receipts, evidence}; cl_route: {task} (the candidate is the layer asked about)
    Returns ``{"answer", "confidence", "escalate", "agrees", "source", "ms"}``. ``escalate`` is True whenever LAYA
    is not confident above the 0.95 gate (or unavailable): then run the big-model check as before.
    ``agrees`` says whether LAYA's answer equals the candidate (None when it escalated). Never raises.
    """
    from pathlib import Path
    root = Path(root) if root else Path.cwd()
    started = time.monotonic()
    from .laya_instant import query
    domain = 'retention' if question == 'repair_retention' else 'verify:' + question
    observation = evidence.get('input', evidence) if question == 'repair_retention' else {'candidate': candidate, 'evidence': evidence}
    if question == 'tool_outcome':
        from .laya_curriculum import outcome_input
        domain, observation = 'outcomes', outcome_input(evidence)
    instant = query(root, domain, observation, user=str(evidence.get('user', '')),
                    **({'labels': [False, True]} if question == 'repair_retention' else {}))
    if not instant.get('escalate'):
        # The episode label is the string 'true'/'false'; compare it the way the service path does.
        if question == 'cl_route':
            agrees = str(instant['answer']).lower() == 'true'
        elif isinstance(candidate, bool):
            agrees = str(instant['answer']).lower() == str(candidate).lower()
        else:
            agrees = instant['answer'] == candidate
        return {**instant, 'agrees': agrees}
    if instant.get('conflict') or instant.get('reason') == 'personal-region-ambiguous':
        return {**instant, 'agrees': None}
    if question in {'repair_retention', 'tool_outcome'}:
        return {**instant, 'agrees': None}
    try:
        if question == "taste_triage":
            verdict = triage_taste(root, evidence, str(evidence.get("pageId", "")))
        elif question == "page_done":
            state = page_done_state(evidence.get("goal"), evidence.get("page"), evidence.get("current"),
                                    evidence.get("action_receipts"), evidence.get("evidence"))
            verdict = decide(root, "page_done", state, timeout_s=timeout_s, label="verify")
        elif question == "cl_route":
            layer = str(candidate)
            verdict = decide(root, "cl_route", route_state(str(evidence.get("task", "")), layer), timeout_s=timeout_s, label="verify:" + layer)
        else:
            return {"answer": None, "confidence": None, "escalate": True, "agrees": None, "source": "unknown-question", "ms": 0}
    except Exception as exc:
        verdict = {"route": "unavailable", "decision": None, "reason": type(exc).__name__}
    answered = verdict.get("route") == "laya" and verdict.get("decision") is not None
    answer = verdict.get("decision") if answered else None
    return {"answer": answer, "confidence": verdict.get("confidence"), "escalate": not answered,
            "agrees": (answer is True if question == "cl_route" else answer == candidate) if answered else None,
            "source": verdict.get("source") or verdict.get("reason"), "ms": round((time.monotonic() - started) * 1000, 1)}


def select_memory(root, candidates):
    """Finite-choice advisory over opaque IDs; deterministic scope/lifecycle wins.

    No learned memory head or automatic outcome admission is claimed. A missing
    or uncertain local service preserves the caller's deterministic cue result.
    """
    from .laya_service import triage
    return triage(root, 'cue-memory', 'Select the most relevant cue match, or none.',
                  [row['id'] for row in candidates] + ['none'], context={'candidates': candidates},
                  path='memory.recall', timeout_s=.25)
