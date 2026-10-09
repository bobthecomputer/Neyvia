"""Append-only correction log and deterministic, checkpoint-scoped memory views."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

import numpy as np

from .contracts import canonical, digest


class Memory:
    def __init__(self, path, capacity=500):
        if not isinstance(capacity, int) or capacity < 1:
            raise ValueError("memory capacity must be a positive integer")
        self.capacity = capacity
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS decisions (
                id TEXT PRIMARY KEY, ts REAL NOT NULL, request_json TEXT NOT NULL,
                identity_json TEXT NOT NULL, response_json TEXT NOT NULL, records_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS outcomes (
                id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, question TEXT NOT NULL,
                ts REAL NOT NULL, correct TEXT NOT NULL, evidence_json TEXT NOT NULL, kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS generations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, reason TEXT NOT NULL,
                active_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS question_sets (
                set_id TEXT PRIMARY KEY, spec_json TEXT NOT NULL, hash TEXT NOT NULL);
        """)
        latest = self.db.execute("SELECT * FROM generations ORDER BY id DESC LIMIT 1").fetchone()
        self.active = set(json.loads(latest["active_json"])) if latest else set()
        self.generation = latest["id"] if latest else 0
        self._cache = {}

    def close(self):
        self.db.close()

    def publish(self, active, reason):
        with self.db:
            cursor = self.db.execute("INSERT INTO generations(ts,reason,active_json) VALUES(?,?,?)",
                                     (time.time(), reason, canonical(sorted(active))))
        self.active, self.generation = set(active), cursor.lastrowid
        self._cache.clear()
        return self.generation

    def log(self, request, identity, response, records):
        decision_id = "d_" + uuid.uuid4().hex
        saved_request = dict(request)
        if not request.get("capture_state", False):
            saved_request["state"] = {"digest_only": digest(request["state"])}
        with self.db:
            self.db.execute("INSERT INTO decisions VALUES(?,?,?,?,?,?)",
                            (decision_id, time.time(), canonical(saved_request), canonical(identity),
                             canonical(response), canonical(records)))
        return decision_id

    def registered_sets(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT spec_json FROM question_sets")]

    def register_set(self, spec, info):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO question_sets VALUES(?,?,?)",
                            (info["set"], canonical(spec), info["hash"]))

    def outcome(self, payload):
        if len(self.active) >= self.capacity:
            raise ValueError(f"active memory capacity {self.capacity} reached; revoke or increase capacity")
        decision = self.db.execute("SELECT records_json FROM decisions WHERE id=?",
                                   (payload["decision_id"],)).fetchone()
        if decision is None:
            raise ValueError("unknown decision_id")
        records = json.loads(decision["records_json"])
        qid = payload.get("question")
        if qid not in records:
            raise ValueError("unknown question for decision")
        record = records[qid]
        if record.get("learning", "instant") != "instant":
            raise ValueError("question does not permit instant correction")
        correct = payload.get("correct")
        if isinstance(correct, bool):
            correct = str(correct).lower()
        else:
            correct = str(correct)
        if correct not in record["labels"]:
            raise ValueError("correct must identify an existing option")
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict) or not evidence.get("receipt") or not evidence.get("verifier"):
            raise ValueError("correction requires evidence receipt and verifier")
        kind = payload.get("kind", "user_correction")
        if kind == "user_correction":
            if evidence["verifier"] != "user":
                raise ValueError("user_correction must be explicitly verified by user")
        elif kind == "verified_effect":
            if evidence.get("passed") is not True or evidence["verifier"] in ("user", "laya", "self"):
                raise ValueError("verified_effect requires independent passed evidence")
        else:
            raise ValueError("only user_correction and verified_effect admit instant learning")
        outcome_id = "o_" + uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO outcomes VALUES(?,?,?,?,?,?,?)",
                            (outcome_id, payload["decision_id"], qid, time.time(), correct,
                             canonical(evidence), kind))
            generation = self.publish(self.active | {outcome_id}, "outcome:" + outcome_id)
        return {"outcome_id": outcome_id, "generation": generation, "durable": True}

    def revoke(self, outcome_id):
        if outcome_id not in self.active:
            raise ValueError("outcome is not active")
        return {"generation": self.publish(self.active - {outcome_id}, "revoke:" + outcome_id),
                "revoked": outcome_id, "durable": True}

    def rollback(self, generation):
        row = self.db.execute("SELECT active_json FROM generations WHERE id=?", (generation,)).fetchone()
        if not row:
            raise ValueError("unknown generation")
        return {"generation": self.publish(set(json.loads(row[0])), "rollback:" + str(generation))}

    def generations(self):
        return [dict(row) for row in self.db.execute(
            "SELECT id,ts,reason FROM generations ORDER BY id")]

    def rows(self, binding=None):
        cache_key = binding or "all"
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = []
        cursor = self.db.execute("""SELECT outcomes.*, decisions.records_json
            FROM outcomes JOIN decisions ON outcomes.decision_id=decisions.id ORDER BY outcomes.id""")
        for row in cursor:
            if row["id"] not in self.active:
                continue
            record = json.loads(row["records_json"])[row["question"]]
            if binding and record["binding"] != binding:
                continue
            result.append({**record, "outcome_id": row["id"], "correct": row["correct"],
                           "decision_id": row["decision_id"],
                           "evidence": json.loads(row["evidence_json"])})
        self._cache[cache_key] = result
        return result

    def apply(self, record, base, features):
        rows = self.rows(record["binding"])
        metadata = {"source": "laya", "evidence": [], "conflict": False,
                    "confidence_kind": "base_model", "novelty": 1.0}
        if not rows:
            return base.copy(), metadata
        exact = [row for row in rows if row["view_digest"] == record["view_digest"]]
        if exact:
            outcomes = {row["correct"] for row in exact}
            metadata["evidence"] = [{"outcome_id": row["outcome_id"], "level": "M0"} for row in exact]
            if len(outcomes) > 1:
                return base.copy(), {**metadata, "source": "escalated", "conflict": True}
            correct = next(iter(outcomes))
            return {key: float(key == correct) for key in base}, {
                **metadata, "source": "m0", "novelty": 0.0,
                "confidence_kind": "verified_exact_match_not_calibrated"}
        signature = record.get("transfer_digest")
        if signature:
            matches = [row for row in rows if row.get("transfer_digest") == signature]
            outcomes = {row["correct"] for row in matches}
            if len(outcomes) > 1:
                return base.copy(), {**metadata, "source": "escalated", "conflict": True,
                                     "admission": "abstract_correction_conflict",
                                     "evidence": [{"outcome_id": row["outcome_id"], "level": "M1"} for row in matches]}
            if outcomes:
                correct = next(iter(outcomes))
                support = {row["view_digest"] for row in matches}
                contrast = [row for row in rows if row.get("transfer_digest") and
                            row["transfer_digest"] != signature and row["correct"] != correct]
                if len(support) >= 2 and contrast:
                    return {key: float(key == correct) for key in base}, {
                        **metadata, "source": "m1", "novelty": 0.0,
                        "confidence_kind": "verified_abstract_match_not_calibrated",
                        "evidence": [{"outcome_id": row["outcome_id"], "level": "M1"} for row in matches],
                        "contrast": [row["outcome_id"] for row in contrast],
                        "admission": "explicit_features_distinct_support_and_contrast"}
        if features is None:
            return base.copy(), metadata
        features = np.asarray(features, dtype=np.float64)
        query = features.reshape(-1).copy()
        query /= max(np.linalg.norm(query), 1e-12)
        neighbours, near_misses = [], []
        for row in rows:
            saved = np.asarray(row["features"], dtype=np.float64)
            if saved.shape != features.shape:
                continue
            vector = saved.reshape(-1)
            similarity = float(query @ vector / max(np.linalg.norm(vector), 1e-12))
            if similarity >= 0.90:
                neighbours.append((similarity, row, saved))
            else:
                near_misses.append(row)
        neighbours.sort(key=lambda item: (-item[0], item[1]["outcome_id"]))
        neighbours = neighbours[:8]
        if not neighbours:
            return base.copy(), metadata
        outcomes = {row["correct"] for _, row, _ in neighbours}
        metadata.update(novelty=1.0 - neighbours[0][0], evidence=[
            {"outcome_id": row["outcome_id"], "level": "M2", "similarity": sim}
            for sim, row, _ in neighbours])
        if len(outcomes) > 1:
            return base.copy(), {**metadata, "source": "escalated", "conflict": True}
        correct = next(iter(outcomes))
        unique_support = {row["view_digest"] for _, row, _ in neighbours}
        # Transfer requires distinct supporting observations and an independently
        # corrected contrasting observation outside the admitted neighbourhood.
        # Repeating an exact state never manufactures generalization evidence.
        has_contrast = any(row["correct"] != correct for row in near_misses)
        if len(unique_support) < 2 or not has_contrast:
            return base.copy(), {**metadata, "admission": "insufficient_support_or_near_miss"}
        # Option-aligned residual scorer, rebuilt from immutable active rows. The
        # dual solve costs O(number of correction options), not O(feature_dim^3).
        keys = record["labels"]
        matrices, targets = [], []
        for _, row, saved in neighbours:
            matrices.append(saved)
            target = np.array([float(key == row["correct"]) - 1 / len(keys) for key in keys])
            targets.append(3.0 * target)
        x = np.concatenate(matrices)
        y = np.concatenate(targets)
        weights = x.T @ np.linalg.solve(x @ x.T + np.eye(len(x)), y)
        alpha = len(neighbours) / (len(neighbours) + 2.0)
        logits = np.log(np.maximum([base[key] for key in keys], 1e-12)) + alpha * (features @ weights)
        logits -= logits.max()
        corrected = np.exp(logits)
        corrected /= corrected.sum()
        vote = np.zeros(len(keys))
        for similarity, row, _ in neighbours:
            vote[keys.index(row["correct"])] += similarity
        vote /= vote.sum()
        beta = min(0.65, alpha * neighbours[0][0])
        corrected = (1 - beta) * corrected + beta * vote
        return dict(zip(keys, map(float, corrected))), {
            **metadata, "source": "laya+head", "confidence_kind": "memory_blend_uncalibrated"}


def make_record(question, state, scope, identity, set_hash, features):
    from .contracts import labels, transfer_signature
    view = question.get("view")
    observed = {key: state.get(key) for key in view} if view and isinstance(state, dict) else state
    qhash = digest({"question": question, "option_order": labels(question),
                    "identity": identity, "set": set_hash})
    return {"binding": digest({"question_hash": qhash, "scope": scope}),
            "question_hash": qhash, "scope": scope, "view_digest": digest(observed),
            "labels": labels(question), "features": None if features is None else features.tolist(),
            "learning": question.get("learning", "instant"),
            "transfer_digest": transfer_signature(question, observed)}
