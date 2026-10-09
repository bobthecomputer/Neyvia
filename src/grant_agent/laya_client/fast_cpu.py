"""Resident adapter for the existing, hash-verified LAYA R5 CPU family.

This loads the selected published local candidate, rather than constructing a
replacement heuristic. Model, source and genes all participate in identity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import threading
import time

from .contracts import QuestionSets, digest, labels


class FastCPU:
    def __init__(self, project, candidate="g3-c2"):
        project = Path(project).resolve(strict=True)
        candidates = json.loads((project / "evidence/r5/candidates.json").read_text(encoding="utf-8"))
        selected = [row for row in candidates.values() if row["label"] == candidate]
        if len(selected) != 1:
            raise ValueError("Select one existing LAYA R5 candidate")
        selected = selected[0]
        model = Path(selected["model"]).resolve(strict=True)
        if not model.is_relative_to(project):
            raise ValueError("The selected checkpoint must remain inside the LAYA project")
        genes = selected["architecture"]["execution_genes"]
        sys.path.insert(0, str(project))
        from laya_system1.round5_state import Round5State
        from laya_system1.shared_state import chunks
        self.runtime = Round5State(model, genes)
        self.chunks = chunks
        self.sets = QuestionSets(project / "question_sets")
        sources = ["contracts.py", "shared_state.py", "evolved_state.py", "round5_state.py", "memory.py"]
        self.identity = {**self.runtime.identity, "candidate": candidate,
                         "candidate_genes": genes, "weights_frozen": True,
                         "source_sha256": {name: hashlib.sha256((project / "laya_system1" / name).read_bytes()).hexdigest() for name in sources},
                         "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         "state_cache": False, "answer_memory": False,
                         "execution_authority": "advisory_only"}
        self.lock = threading.Lock()
        self.count = 0
        self.started_at = time.time()

    def decide(self, request):
        if "state" not in request:
            raise ValueError("state is required")
        questions, set_hash = self.sets.resolve(request)
        if len(questions) > 12 or len(json.dumps(request, ensure_ascii=False)) > 200_000:
            raise ValueError("Decision exceeds the bounded CPU request budget")
        started = time.perf_counter()
        with self.lock:
            # Always run inference. Neither fitted labels nor benchmark answers
            # enter the resident model or an answer cache.
            response, _ = self.runtime.predict(request["state"], questions, cache=False)
            for qid, question in questions.items():
                raw = response["answers"][qid]
                if question["type"] == "noul":
                    p = {"false": 1-float(raw["noul"]), "true": float(raw["noul"])}
                else:
                    p = raw["probabilities"]
                if set(p) != set(labels(question)):
                    raise ValueError("Model returned mismatched option identities")
                best = max(p, key=p.get)
                threshold = question.get("thresholds", {}).get("answer", 0)
                response["answers"][qid] = {**raw, "p": p, "p_base": p.copy(), "answer": best,
                    "top_probability": p[best], "source": "laya", "policy": "answer" if p[best] >= threshold else "escalate"}
            self.count += 1
            response.update(identity=self.identity, memory_enabled=False, base_cache=False,
                            decision_id=f"fast-cpu-{self.count}", durable=False, set_hash=set_hash)
            response["runtime"].update(execution="cpu-only-r5", state_cache_hits=0)
            response["runtime"]["truncated_state_chunks"] = sum(max(0, len(self.chunks(
                {key: request["state"].get(key) for key in question["view"]}
                if question.get("view") and isinstance(request["state"], dict) else request["state"]))
                - self.runtime.manifest["chunk_cap"]) for question in questions.values())
            response["latency_ms"] = {"total": (time.perf_counter()-started)*1000,
                                      "model": response["runtime"]["total_ms"]}
            return response

    def health(self):
        return {"status": "ready", "identity": self.identity, "pid": __import__("os").getpid(),
                "requests_measured": self.count, "uptime_s": time.time()-self.started_at,
                "weights_frozen": True, "identity_digest": digest(self.identity)}
