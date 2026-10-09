"""Versioned typed decisions and an injectable T20 hook; no app dependencies."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from pathlib import Path


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
                      allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def labels(question):
    kind = question.get("type")
    criteria = question.get("criteria")
    if kind == "noul":
        return ["false", "true"]
    if kind == "choice" and isinstance(criteria, dict) and len(criteria) >= 2:
        return list(criteria)
    if kind == "score" and isinstance(criteria, list) and len(criteria) >= 2:
        return [str(i) for i in range(len(criteria))]
    raise ValueError("question requires noul, choice criteria mapping, or score criteria list")


def transfer_signature(question, state):
    """Explicit question-scoped abstractions; missing inputs never match memory."""
    spec = question.get("transfer_features")
    if spec is None:
        return None
    if not isinstance(spec, dict) or not 1 <= len(spec) <= 32:
        raise ValueError("transfer_features requires 1 to 32 named feature definitions")
    result = {}
    for name, feature in spec.items():
        if not isinstance(feature, dict):
            raise ValueError("transfer feature requires a definition object")
        expected_keys = {"path", "op", "value_path"} if feature.get("op") == "contains_path" else {"path", "op"}
        if set(feature) != expected_keys:
            raise ValueError("transfer feature requires path and op, plus value_path for contains_path")
        path, op = feature["path"], feature["op"]
        if not isinstance(path, list) or not 1 <= len(path) <= 16 or any(not isinstance(k, str) for k in path):
            raise ValueError("transfer path requires 1 to 16 object keys")
        if op not in {"exact", "nonempty", "nonempty_each", "contains_path"}:
            raise ValueError("unknown transfer feature operation")
        if op == "contains_path":
            value_path = feature["value_path"]
            if not isinstance(value_path, list) or not 1 <= len(value_path) <= 16 or any(not isinstance(k, str) for k in value_path):
                raise ValueError("transfer value_path requires 1 to 16 object keys")
    for name, feature in spec.items():
        path, op = feature["path"], feature["op"]
        value = state
        for key in path:
            if not isinstance(value, dict) or key not in value:
                return None
            value = value[key]
        if op == "contains_path":
            expected = state
            for key in feature["value_path"]:
                if not isinstance(expected, dict) or key not in expected:
                    return None
                expected = expected[key]
            if not isinstance(value, str) or not isinstance(expected, str) or not expected.strip():
                return None
            value = expected in value
        elif op == "nonempty_each":
            if not isinstance(value, dict) or not value:
                return None
            value = {key: item is not None and item != "" for key, item in value.items()}
        elif op == "nonempty":
            value = value is not None and value != ""
        result[name] = value
    return digest(result)


def validate_questions(questions):
    if not isinstance(questions, dict) or not questions:
        raise ValueError("questions must be a nonempty object")
    for qid, question in questions.items():
        if not isinstance(qid, str) or not isinstance(question, dict):
            raise ValueError("each question must have a string ID and object definition")
        if not isinstance(question.get("instructions"), str) or not question["instructions"].strip():
            raise ValueError("question instructions must be nonempty")
        labels(question)
        # Validate the feature specification independently of state availability.
        if "transfer_features" in question:
            transfer_signature(question, {})
    return questions


def probabilities(answer, question):
    keys = labels(question)
    if question["type"] == "noul":
        p = float(answer["noul"])
        return {"false": 1.0 - p, "true": p}
    probs = answer["probabilities"]
    return {key: float(probs[key]) for key in keys}


def native_answer(question, probs):
    kind = question["type"]
    best = max(probs, key=probs.get)
    result = {"type": kind, "probabilities": probs}
    if kind == "noul":
        result["noul"] = probs["true"]
    else:
        result["choice" if kind == "choice" else "score"] = (
            best if kind == "choice" else sum(int(key) * p for key, p in probs.items()))
    return result


class QuestionSets:
    def __init__(self, directory=None):
        self.sets = {}
        if directory:
            for path in sorted(Path(directory).glob("*.json")):
                self.register(json.loads(path.read_text(encoding="utf-8")))

    def register(self, spec):
        validate_questions(spec.get("questions"))
        if not isinstance(spec.get("id"), str) or not isinstance(spec.get("version"), int):
            raise ValueError("question set requires id and integer version")
        key = f"{spec['id']}@{spec['version']}"
        sha = digest(spec)
        if key in self.sets and self.sets[key]["hash"] != sha:
            raise ValueError("question set version is immutable; increment version")
        self.sets[key] = {"hash": sha, "spec": spec}
        return {"set": key, "hash": sha}

    def resolve(self, request):
        if not request.get("set"):
            return validate_questions(request.get("questions")), "ad-hoc"
        entry = self.sets[request["set"]]
        available = entry["spec"]["questions"]
        selected = request.get("questions") or list(available)
        if not isinstance(selected, list):
            raise ValueError("registered set questions must be a list of IDs")
        return validate_questions({key: available[key] for key in selected}), entry["hash"]


class T20Hook:
    """Callable installed by T20 only. Reject stale observations before inference."""
    def __init__(self, endpoint="http://127.0.0.1:8796", max_age_ms=5000,
                 timeout_s=30, transport=None):
        self.endpoint = endpoint.rstrip("/")
        self.max_age_ms = max_age_ms
        self.timeout_s = timeout_s
        self.transport = transport or self._post

    def _post(self, payload):
        request = urllib.request.Request(self.endpoint + "/v1/decide",
                                         canonical(payload).encode(),
                                         {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            return json.load(response)

    def __call__(self, call):
        if not isinstance(call.get("tabId"), (str, int)) or isinstance(call.get("tabId"), bool) or call["tabId"] == "":
            raise ValueError("hook requires a tabId")
        state = call.get("observed")
        if not isinstance(state, dict) or state.get("revision") is None:
            raise ValueError("observed CL-State requires revision")
        observed_at = state.get("observed_at_ms")
        if not isinstance(observed_at, (float, int)):
            raise ValueError("observed CL-State requires observed_at_ms epoch timestamp")
        age = time.time() * 1000 - observed_at
        if age < -1000 or age > self.max_age_ms:
            raise ValueError("observed CL-State is stale or has a future timestamp")
        question = call.get("question")
        if isinstance(question, str):
            payload = {"set": "neyvia.cl-state@1", "questions": [question]}
        elif isinstance(question, dict):
            payload = {"questions": {"decision": question}}
        else:
            raise ValueError("hook question must be a registered ID or typed question")
        payload.update(state=state, client="t20-laya-hook",
                       scope={"tabId": call.get("tabId"), "domain": "CL-State"})
        response = self.transport(payload)
        response["observation"] = {"revision": state["revision"],
                                   "digest": digest(state), "age_ms": age}
        return response
