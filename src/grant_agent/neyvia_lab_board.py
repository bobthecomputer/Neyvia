"""Read existing frozen improvement receipts; Pareto sets never imply promotion."""
from __future__ import annotations

import json
import math

DEFINITIONS = [("lab.state", "Read actual improvement history, frozen competitions and measured Pareto sets. Does not train or promote.", {}, [])]


def vector(candidate):
    values = {}
    for row in candidate.get("measurements", []):
        key = next((key for key in ("value", "meanMs", "bytes") if key in row), None)
        value = row.get(key) if key else None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return None
        values[row["instrument"]] = value
    return values or None


def pareto(candidates):
    measured = [(row, vector(row)) for row in candidates if row.get("eligible")]
    result = []
    for row, point in measured:
        if not point:
            continue
        dominated = any(other and other.keys() == point.keys() and all(other[key] <= point[key] for key in point)
                        and any(other[key] < point[key] for key in point) for _, other in measured)
        if not dominated:
            result.append(row["candidate"])
    return result


def state(root):
    from .improvement_lab import ImprovementLab
    lab = ImprovementLab(root)
    status = lab.status()
    competitions = []
    for row in status["records"]:
        if row["status"] != "recorded":
            continue
        value = json.loads((lab.base / row["path"]).read_text(encoding="utf-8"))
        if value.get("kind") == "competition":
            competitions.append({key: value.get(key) for key in ("receiptId", "competitionId", "definitionHash", "observedAt", "candidates", "boundary")})
            competitions[-1]["pareto"] = pareto(value.get("candidates", []))
    from .neyvia_evolver import state as evolver_state
    return {"ok": True, **status, "competitions": competitions, "scope": "Latest 50 legacy records plus durable domain-specific Evolver trials",
            "automaticTraining": False, "automaticPromotion": False, "semanticQualityVerified": False,
            "evolver": evolver_state(root)}
