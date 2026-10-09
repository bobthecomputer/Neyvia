"""Context-bound correction history and observable attention experiments."""

from __future__ import annotations
import hashlib, json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from .durability import atomic_write_json
from .harness_jobs import _exclusive_job_lock
from .behavioral_experiments import BehavioralExperimentLedger

CONTEXTS = {"landing-page", "product-ui", "research", "game"}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(v):
    return hashlib.sha256(
        json.dumps(
            v, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


def _file_hash(root, path):
    p = (root / Path(path)).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError("artifact path escapes scoped root") from e
    if not p.is_file() or p.is_symlink():
        raise ValueError("artifact must be a real scoped file")
    return (
        p.relative_to(root.resolve()).as_posix(),
        hashlib.sha256(p.read_bytes()).hexdigest(),
    )


class ContextualLearningStore:
    def __init__(self, path, *, scope_root):
        self.path = Path(path).resolve()
        self.scope_root = Path(scope_root).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._read()

    def _read(self):
        if not self.path.is_file():
            return {
                "schema": "neyvia.contextual_learning.v1",
                "corrections": {},
                "preferences": {},
                "events": [],
                "integrity": _hash(
                    {"corrections": {}, "preferences": {}, "events": []}
                ),
            }
        s = json.loads(self.path.read_text(encoding="utf-8"))
        if s.get("schema") != "neyvia.contextual_learning.v1":
            raise ValueError("unsupported contextual learning schema")
        body = {
            "corrections": s.get("corrections", {}),
            "preferences": s.get("preferences", {}),
            "events": s.get("events", []),
        }
        if s.get("integrity") != _hash(body):
            raise ValueError("contextual learning state tampered")
        return s

    @contextmanager
    def _locked(self):
        with _exclusive_job_lock(self.path):
            yield

    def _save(self):
        self.state["integrity"] = _hash(
            {
                "corrections": self.state.get("corrections", {}),
                "preferences": self.state.get("preferences", {}),
                "events": self.state.get("events", []),
            }
        )
        atomic_write_json(self.path, self.state)

    def record_correction(
        self, context, *, before_path, after_path, correction, agent_id=""
    ):
        if context not in CONTEXTS:
            raise ValueError("unsupported context")
        before, bhash = _file_hash(self.scope_root, before_path)
        after, ahash = _file_hash(self.scope_root, after_path)
        if not str(correction or "").strip():
            raise ValueError("correction is required")
        pair = _hash({"context": context, "before": bhash, "after": ahash})
        with self._locked():
            self.state = self._read()
            existing = self.state["corrections"].get(pair[:24])
            if existing:
                return existing
            row = {
                "correctionId": pair[:24],
                "context": context,
                "before": {"path": before, "sha256": bhash},
                "after": {"path": after, "sha256": ahash},
                "correction": str(correction),
                "agentId": str(agent_id),
                "status": "provisional",
                "trustedOperator": False,
                "recordedAt": _now(),
            }
            self.state["corrections"][row["correctionId"]] = row
            self.state.setdefault("events", []).append(
                {
                    "type": "correction_recorded",
                    "correctionId": row["correctionId"],
                    "at": row["recordedAt"],
                }
            )
            self._save()
            return row

    def record_preference(self, correction_id, *, preference, source):
        if str(source).strip().lower() not in {"operator", "trusted_operator"}:
            raise ValueError("only trusted operator may record preference")
        if not isinstance(preference, bool):
            raise ValueError("preference must be an explicit operator boolean")
        with self._locked():
            self.state = self._read()
            row = self.state["corrections"].get(correction_id)
            if not row:
                raise KeyError(correction_id)
            for side in ('before','after'):
                _, observed_hash = _file_hash(self.scope_root, row[side]['path'])
                if observed_hash != row[side]['sha256']:
                    raise ValueError('Correction artifact changed before operator review')
            row.update(
                {
                    "status": "accepted" if preference else "rejected",
                    "trustedOperator": True,
                    "operatorPreference": preference,
                    "preferenceRecordedAt": _now(),
                }
            )
            self.state["preferences"][correction_id] = {
                "preference": preference,
                "source": "trusted_operator",
                "recordedAt": row["preferenceRecordedAt"],
            }
            self.state.setdefault("events", []).append(
                {
                    "type": "operator_preference",
                    "correctionId": correction_id,
                    "preference": preference,
                    "at": row["preferenceRecordedAt"],
                }
            )
            self._save()
            return row

    def history(self, context, *, correction=None, limit=100):
        rows = [
            r
            for r in self._read()["corrections"].values()
            if r["context"] == context
            and (correction is None or r["correction"] == correction)
        ][: max(0, min(int(limit), 200))]
        pairs = {r["correctionId"] for r in rows}
        uncertainty = (
            "no_evidence"
            if not rows
            else (
                "provisional"
                if any(not r.get("trustedOperator") for r in rows)
                else "operator-confirmed"
            )
        )
        return {
            "context": context,
            "rows": rows,
            "sampleCount": len(rows),
            "uniquePairCount": len(pairs),
            "uncertainty": uncertainty,
            "independentSupport": False,
        }

    def create_attention_experiment(
        self,
        experiment_id,
        *,
        baseline_input,
        variant_input,
        acceptance,
        requested_route,
        budget,
        seed=None,
    ):
        return BehavioralExperimentLedger(
            self.path.with_name(self.path.stem + "-attention.json")
        ).create(
            experiment_id,
            baseline_input=baseline_input,
            variant_input=variant_input,
            acceptance=acceptance,
            requested_route=requested_route,
            budget=budget,
            seed=seed,
        )

    def record_attention_observation(self, experiment_id, **kwargs):
        return BehavioralExperimentLedger(
            self.path.with_name(self.path.stem + "-attention.json")
        ).record(experiment_id, **kwargs)

    def compare_attention(self, experiment_id):
        result = BehavioralExperimentLedger(
            self.path.with_name(self.path.stem + "-attention.json")
        ).compare(experiment_id)
        result["representationClaim"] = (
            "observable quality only; private internal state was not measured"
        )
        return result

    def select_representation(
        self, experiment_id, *, protected_constraints=None, token_budget=1800
    ):
        constraints = protected_constraints if protected_constraints is not None else {}
        if len(json.dumps(constraints, ensure_ascii=False)) > int(token_budget) * 4:
            raise ValueError(
                "Protected constraints exceed projection budget; retrieve a larger context"
            )
        result = self.compare_attention(experiment_id)
        result["protectedConstraints"] = constraints
        if result.get("status") != "compared" or not result.get("pairs"):
            result.update({"recommendation": "inconclusive", "autoPromote": False})
            return result
        ledger = BehavioralExperimentLedger(
            self.path.with_name(self.path.stem + "-attention.json")
        )
        criterion = ledger._read()["experiments"][experiment_id]["definition"][
            "acceptance"
        ]
        if criterion["kind"] != "response_contains":
            result.update(recommendation="inconclusive", autoPromote=False)
            return result
        needle = criterion["text"]
        baseline = sum(
            needle in str(pair["baseline"]["response"]) for pair in result["pairs"]
        )
        variant = sum(
            needle in str(pair["variant"]["response"]) for pair in result["pairs"]
        )
        result.update(
            recommendation=(
                "tie"
                if baseline == variant
                else "variant" if variant > baseline else "baseline"
            ),
            autoPromote=False,
            baselinePasses=baseline,
            variantPasses=variant,
        )
        return result
