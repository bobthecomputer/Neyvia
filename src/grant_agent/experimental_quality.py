"""Sealed, evidence-only quality instruments and counterfactual comparisons."""

from __future__ import annotations
import hashlib, json, time
import math, uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any
from .durability import atomic_write_json
from .harness_jobs import _exclusive_job_lock
from .visual_specifications import inspect_image


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class ExperimentalQuality:
    def __init__(self, root: str | Path, work_id=None):
        self.root = Path(root).resolve()
        self.base = self.root / ".agent_control" / "quality"
        if work_id is not None:
            self.base = self.base / self._safe(work_id)
        self.base.mkdir(parents=True, exist_ok=True)

    def _safe(self, v):
        if (
            not isinstance(v, str)
            or not v
            or len(v) > 120
            or v in {".", ".."}
            or any(
                c
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
                for c in v
            )
        ):
            raise ValueError("unsafe id")
        return v

    def _definition(self, kind, identity):
        p = self.base / f"{kind}-{self._safe(identity)}.json"
        d = json.loads(p.read_text(encoding="utf-8"))
        if (
            d.get("id") != identity
            or d.get("hash")
            != hashlib.sha256(
                json.dumps(d.get("spec"), sort_keys=True, allow_nan=False).encode()
            ).hexdigest()
        ):
            raise ValueError("definition integrity mismatch")
        return d

    def _seal(self, kind, identity, spec, *, catalog_locked=False):
        p = self.base / f"{kind}-{self._safe(identity)}.json"
        raw = json.dumps(spec, sort_keys=True, allow_nan=False)
        if len(raw) > 64000:
            raise ValueError("definition too large")
        with (
            nullcontext()
            if catalog_locked
            else _exclusive_job_lock(self.base / "catalog.json")
        ):
            if p.exists():
                raise FileExistsError("definition sealed")
            atomic_write_json(
                p,
                {
                    "schema": f"neyvia.quality.{kind}.v1",
                    "id": identity,
                    "spec": spec,
                    "sealed": True,
                    "hash": hashlib.sha256(raw.encode()).hexdigest(),
                },
            )
        return str(p)

    def _receipt(self, value):
        value = {**value, "receiptId": uuid.uuid4().hex, "observedAt": time.time()}
        p = self.base / f"receipt-{value['receiptId']}.json"
        value["receiptPath"] = str(p)
        atomic_write_json(p, value)
        return value

    def define_instrument(self, i: str, spec: dict[str, Any]):
        if spec.get("kind") not in {"json_numeric", "image", "trace_timing"}:
            raise ValueError("unsupported instrument")
        if spec["kind"] == "json_numeric" and (
            not spec.get("key") or "max" not in spec
        ):
            raise ValueError("key and maximum required")
        for key in ("max", "maxMeanMs", "maxBytes", "minWidth", "minHeight"):
            if key in spec and (
                isinstance(spec[key], bool)
                or not isinstance(spec[key], (int, float))
                or not math.isfinite(spec[key])
            ):
                raise ValueError("finite numeric limit required")
        return self._seal("instrument", i, spec)

    def define_holdout(self, i: str, spec: dict[str, Any]):
        if i.startswith("challenge-"):
            raise ValueError(
                "Challenge examination identities require operator promotion"
            )
        return self._seal("holdout", i, spec)

    def measure(self, instrument: str, target: str | Path) -> dict[str, Any]:
        d = self._definition("instrument", instrument)
        p = (self.root / target).resolve()
        p.relative_to(self.root)
        if not p.is_file():
            raise ValueError("target missing")
        if p.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("measurement input exceeds 32 MB")
        spec = d["spec"]
        out = {"instrument": instrument, "path": str(p), "sha256": _sha(p)}
        if spec.get("kind") == "image":
            out.update(inspect_image(p))
            out["bytes"] = p.stat().st_size
            out["withinLimit"] = (
                out["dimensions"]["width"] >= spec.get("minWidth", 0)
                and out["dimensions"]["height"] >= spec.get("minHeight", 0)
                and out["bytes"] <= spec.get("maxBytes", float("inf"))
            )
        elif spec.get("kind") == "json_numeric":
            val = json.loads(p.read_text())
            key = spec.get("key")
            raw = val[key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError("numeric measurement required")
            num = float(raw)
            if not math.isfinite(num):
                raise ValueError("numeric measurement is not finite")
            out["value"] = num
            out["withinLimit"] = num <= float(spec["max"])
        elif spec.get("kind") == "trace_timing":
            rows = json.loads(p.read_text())
            durations = [x['durationMs'] for x in rows]
            if not durations or not all(
                not isinstance(x,bool) and isinstance(x,(int,float)) and math.isfinite(x) and x>=0 for x in durations
            ):
                raise ValueError("invalid trace")
            out['sampleCount']=len(durations)
            out['durationsMs']=durations[:100]
            out['omittedSamples']=max(0,len(durations)-100)
            out['retrieval']={'path':str(p),'sha256':out['sha256']}
            out["meanMs"] = math.fsum(durations) / len(durations)
            out["withinLimit"] = out["meanMs"] <= spec.get("maxMeanMs", float("inf"))
        else:
            raise ValueError("unsupported instrument")
        return self._receipt(out)

    def compare(
        self, instrument: str, baseline: str | Path, candidate: str | Path
    ) -> dict[str, Any]:
        a = self.measure(instrument, baseline)
        b = self.measure(instrument, candidate)
        return self._receipt(
            {
                "baseline": a,
                "candidate": b,
                "regression": bool(a["withinLimit"] and not b["withinLimit"]),
                "status": "accepted" if b["withinLimit"] else "rejected",
                "claim": "declared instrument criteria only",
            }
        )

    def challenge(
        self, holdout: str, proposal: dict[str, Any], trusted_operator: bool = False
    ):
        if trusted_operator:
            raise PermissionError("Use authenticated operator review")
        h = self._definition("holdout", holdout)
        q = self.base / f"challenge-{uuid.uuid4().hex}.json"
        out = {
            "id": q.stem,
            "holdout": holdout,
            "proposal": proposal,
            "status": "pending_operator_promotion",
        }
        atomic_write_json(q, out)
        if not trusted_operator:
            return out
        raise PermissionError(
            "trusted promotion must use a separate operator authority call"
        )

    def review_challenge(self, challenge_id, *, approve, operator_identity):
        if not operator_identity or not isinstance(approve, bool):
            raise ValueError("Authenticated operator and decision required")
        p = self.base / f"{self._safe(challenge_id)}.json"
        if not challenge_id.startswith("challenge-"):
            raise ValueError("Challenge identity required")
        with _exclusive_job_lock(self.base / "catalog.json"):
            value = json.loads(p.read_text(encoding="utf-8"))
            self._definition("holdout", value["holdout"])
            if value["status"] != "pending_operator_promotion":
                raise ValueError("Challenge already reviewed")
            if approve:
                spec = value["proposal"].get("spec")
                instruments = (
                    spec.get("instruments", []) if isinstance(spec, dict) else []
                )
                if not instruments or len(instruments) > 20:
                    raise ValueError(
                        "Challenge needs an executable instrument specification before promotion"
                    )
                for instrument in instruments:
                    self._definition("instrument", instrument)
                promoted_path = self.base / f"holdout-{challenge_id}.json"
                if promoted_path.exists():
                    if self._definition("holdout", challenge_id)["spec"] != spec:
                        raise ValueError(
                            "Promoted definition does not match reviewed challenge"
                        )
                else:
                    self._seal("holdout", challenge_id, spec, catalog_locked=True)
                value["promotedHoldoutId"] = challenge_id
            value.update(
                status="approved" if approve else "rejected",
                reviewedBy=operator_identity,
                reviewedAt=time.time(),
            )
            atomic_write_json(p, value)
        return value

    def examine(self, holdout, targets):
        if holdout.startswith("challenge-"):
            review = json.loads(
                (self.base / f"{self._safe(holdout)}.json").read_text(encoding="utf-8")
            )
            if (
                review.get("status") != "approved"
                or review.get("promotedHoldoutId") != holdout
            ):
                raise PermissionError("Challenge promotion has not completed")
        spec = self._definition("holdout", holdout)["spec"]
        instruments = spec.get("instruments", [])
        if not instruments or len(instruments) > 20 or not targets or len(targets) > 20:
            raise ValueError("Bounded instruments and targets required")
        measurements = [
            self.measure(i, target) for i in instruments for target in targets
        ]
        return self._receipt(
            {
                "holdout": holdout,
                "measurements": measurements,
                "passed": all(row["withinLimit"] for row in measurements),
                "claim": "frozen declared criteria; not general model quality",
            }
        )

    def list_challenges(self, *, limit=30):
        paths = sorted(
            self.base.glob("challenge-*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        rows = []
        for path in paths[: max(1, min(int(limit), 100))]:
            value = json.loads(path.read_text(encoding="utf-8"))
            rows.append(value)
        return {"rows": rows, "omittedCount": max(0, len(paths) - len(rows))}
