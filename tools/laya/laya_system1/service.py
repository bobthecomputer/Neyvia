"""Local System One HTTP service. Frozen model predictions plus reversible memory."""
from __future__ import annotations

import argparse
import copy
import json
import math
import threading
import time
from collections import OrderedDict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np

from .contracts import QuestionSets, canonical, digest, labels, native_answer, probabilities
from .memory import Memory, make_record


class Engine:
    def __init__(self, runtime, database, question_sets=None, memory_capacity=500):
        self.runtime = runtime
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        self.memory = Memory(database, capacity=memory_capacity)
        self.sets = QuestionSets(question_sets)
        for spec in self.memory.registered_sets():
            self.sets.register(spec)
        self.lock = threading.RLock()
        self.timings = deque(maxlen=10000)
        self.started_at = time.time()
        self.base_cache = OrderedDict()

    def predict(self, state, questions, cache=True):
        viewed = {qid: {key: state.get(key) for key in question["view"]}
                  if question.get("view") and isinstance(state, dict) else state
                  for qid, question in questions.items()}
        key = digest([self.runtime.identity, questions, viewed,
                      {qid: labels(question) for qid, question in questions.items()}])
        if cache and key in self.base_cache:
            self.base_cache.move_to_end(key)
            response, features = self.base_cache[key]
            response = copy.deepcopy(response)
            response["runtime"] = {"execution": "exact_base_cache", "total_ms": 0.0,
                                   "forward_ms": 0.0, "tokenization_ms": 0.0,
                                   "truncated_state_tokens": response["runtime"]["truncated_state_tokens"]}
            response["usage"] = {"input_tokens": 0, "output_tokens": 0}
            return response, features
        response, features = self.runtime.predict(state, questions)
        if cache:
            self.base_cache[key] = (copy.deepcopy(response), features)
            if len(self.base_cache) > 500:
                self.base_cache.popitem(last=False)
        return response, features

    def decide(self, request, use_memory=True):
        started = time.perf_counter()
        if "state" not in request:
            raise ValueError("state is required")
        with self.lock:
            questions, set_hash = self.sets.resolve(request)
            scope = request.get("scope", {})
            if not isinstance(scope, dict):
                raise ValueError("scope must be an object")
            # An identical frozen question/view can reuse its base distribution;
            # benchmark routes always run actual inference with this cache off.
            response, features = self.predict(request["state"], questions,
                                               cache=request.get("base_cache", False) and use_memory)
            records = {}
            generation = self.memory.generation
            for qid, question in questions.items():
                record = make_record(question, request["state"], scope, self.runtime.identity,
                                     set_hash, features.get(qid))
                record["set"] = request.get("set", "ad-hoc")
                records[qid] = record
                base = probabilities(response["answers"][qid], question)
                probs, metadata = self.memory.apply(record, base, features.get(qid)) if use_memory else (
                    base.copy(), {"source": "laya", "evidence": [], "conflict": False,
                                  "confidence_kind": "base_model", "novelty": 1.0})
                best = max(probs, key=probs.get)
                policy = "escalate" if metadata["conflict"] else "answer"
                thresholds = question.get("thresholds", {})
                if probs[best] < thresholds.get("answer", 0.0):
                    policy = "escalate"
                stakes = question.get("stakes", {})
                if isinstance(stakes, dict):
                    stakes = stakes.get(best, stakes.get("default", "reversible_cheap"))
                if stakes == "irreversible":
                    policy = "ask"
                elif stakes == "reversible_costly" and policy == "answer":
                    policy = "answer+postcheck"
                original = response["answers"][qid]
                entropy = -sum(p * math.log(p) for p in probs.values() if p > 0)
                native_confidence = max(probs.values()) if question["type"] == "noul" else (
                    1.0 - entropy / math.log(len(probs)))
                response["answers"][qid] = {**original, **native_answer(question, probs), "p": probs,
                    "p_base": base, "answer": best, "policy": policy, **metadata,
                    "question_hash": record["question_hash"],
                    "base_confidence": original.get("confidence"),
                    "confidence": native_confidence,
                    "native_confidence_definition": "top_probability" if question["type"] == "noul"
                        else "one_minus_normalized_entropy",
                    "top_probability": probs[best]}
            response.update(generation=generation, identity=self.runtime.identity,
                            set_hash=set_hash, memory_enabled=use_memory)
            response["decision_id"] = self.memory.log(request, self.runtime.identity, response, records)
            response["durable"] = True
            elapsed = (time.perf_counter() - started) * 1000
            response["latency_ms"] = {"total": elapsed,
                                      "model": response.get("runtime", {}).get("total_ms")}
            if request.get("deadline_ms") is not None:
                response["deadline_missed"] = elapsed > float(request["deadline_ms"])
            self.timings.append(elapsed)
            return response

    def health(self):
        with self.lock:
            timings = list(self.timings)
            return {"status": "ready", "identity": self.runtime.identity,
                    "generation": self.memory.generation, "uptime_s": time.time() - self.started_at,
                    "requests_measured": len(timings), "latency_ms": {
                        "p50": float(np.percentile(timings, 50)) if timings else None,
                        "p95": float(np.percentile(timings, 95)) if timings else None},
                    "weights_frozen": True, "execution_authority": "advisory_only",
                    "memory_capacity": self.memory.capacity, "active_outcomes": len(self.memory.active)}

    def close(self):
        self.memory.close()


def create_server(engine, host="127.0.0.1", port=8796):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("System One service only binds loopback")
    if port == 47881:
        raise ValueError("port 47881 is reserved and forbidden")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            # Do not emit request state or correction evidence into console logs.
            pass

        def send_json(self, status, value):
            payload = canonical(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            route = urlsplit(self.path)
            with engine.lock:
                if route.path == "/v1/health":
                    result = engine.health()
                elif route.path == "/v1/question-sets":
                    result = engine.sets.sets
                elif route.path == "/v1/generations":
                    result = {"current": engine.memory.generation, "generations": engine.memory.generations()}
                elif route.path == "/v1/memory":
                    query = parse_qs(route.query)
                    rows = engine.memory.rows()
                    if "set" in query:
                        rows = [row for row in rows if row.get("set") == query["set"][0]]
                    if "scope" in query:
                        scope = json.loads(query["scope"][0])
                        rows = [row for row in rows if row["scope"] == scope]
                    result = {"generation": engine.memory.generation,
                              "rows": [{key: value for key, value in row.items() if key != "features"}
                                       for row in rows]}
                else:
                    self.send_json(404, {"error": "unknown route"})
                    return
            self.send_json(200, result)

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                # A memory bound for an interactive local service; the caller can
                # split large state views instead of exhausting the resident model.
                if length <= 0 or length > 8 * 1024 * 1024:
                    self.close_connection = True
                    self.send_json(413, {"error": "JSON body must be between 1 byte and 8 MiB"})
                    return
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("request must be a JSON object")
                path = urlsplit(self.path).path
                if path in ("/ai/run", "/v1/systemone", "/v1/decide"):
                    # Public benchmark calls are memory-disabled by default.
                    result = engine.decide(payload, use_memory=(path == "/v1/decide" and
                                                                payload.get("memory", True)))
                else:
                    with engine.lock:
                        if path == "/v1/outcome":
                            result = engine.memory.outcome(payload)
                        elif path == "/v1/revoke":
                            result = engine.memory.revoke(payload["outcome_id"])
                        elif path == "/v1/generations/rollback":
                            result = engine.memory.rollback(int(payload["generation"]))
                        elif path == "/v1/question-sets":
                            result = engine.sets.register(payload)
                            engine.memory.register_set(payload, result)
                        else:
                            self.send_json(404, {"error": "unknown route"})
                            return
                self.send_json(200, result)
            except (KeyError, ValueError, TypeError) as exc:
                self.send_json(400, {"error": str(exc), "fallback": False})
            except Exception as exc:
                import traceback
                traceback.print_exc()
                self.send_json(500, {"error": type(exc).__name__ + ": " + str(exc), "fallback": False})

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--port", type=int, default=8796)
    parser.add_argument("--database", default="evidence/system1.sqlite")
    parser.add_argument("--question-sets", default="question_sets")
    parser.add_argument("--calibration")
    parser.add_argument("--encoding", choices=("reference", "prepared"), default="prepared")
    parser.add_argument("--max-len", type=int)
    parser.add_argument("--memory-capacity", type=int, default=500)
    parser.add_argument("--architecture", choices=("transformer", "shared-state"), default="transformer")
    parser.add_argument("--variant", choices=("head", "lexical", "head-only", "latent", "retrieval-only", "retrieval", "conditional", "int8"), default="head")
    args = parser.parse_args()
    Path(args.database).parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    if args.architecture == "shared-state":
        if args.device != "cpu" or args.calibration:
            raise ValueError("shared-state requires CPU and its own train-derived frozen manifest")
        from .shared_state import SharedState
        runtime = SharedState(args.model, variant=args.variant)
    else:
        from .runtime import Runtime
        runtime = Runtime(args.model, device=args.device, calibration=args.calibration,
                          encoding=args.encoding, max_len=args.max_len)
    engine = Engine(runtime, args.database, args.question_sets, args.memory_capacity)
    server = create_server(engine, port=args.port)
    print(canonical({"listening": f"http://127.0.0.1:{args.port}",
                     "cold_start_ms": (time.perf_counter() - started) * 1000,
                     "identity": runtime.identity}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        engine.close()


if __name__ == "__main__":
    main()
