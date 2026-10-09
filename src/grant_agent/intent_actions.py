"""Resolve semantic user intents against fresh observations before acting."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Callable, Iterable

from .verified_operations import VerifiedOperationStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _identity(row: dict[str, Any]) -> str:
    return str(row.get("id") or row.get("targetId") or row.get("identity") or "").strip()


def _matches(row: dict[str, Any], intent: dict[str, Any]) -> bool:
    target = intent.get("target") if isinstance(intent.get("target"), dict) else intent
    for key in ("semanticTarget", "label", "name", "role", "kind"):
        expected = target.get(key)
        if expected is not None and str(row.get(key) or row.get("semanticTarget") or "") != str(expected):
            return False
    acceptable = {str(v) for v in (intent.get("acceptableIds") or target.get("acceptableIds") or [])}
    return not acceptable or _identity(row) in acceptable


class IntentAction:
    """A safe semantic action resolver.

    ``observe`` returns a list of current identity records. ``gateway`` receives
    one payload containing the selected identity and intent. Both are injected so
    browser/native backends cannot be silently substituted here.
    """

    def __init__(self, *, observe: Callable[[], Iterable[dict[str, Any]]],
                 gateway: Callable[[dict[str, Any]], Any],
                 verified_store: VerifiedOperationStore | None = None):
        self.observe = observe
        self.gateway = gateway
        self.verified_store = verified_store

    def resolve(self, intent: dict[str, Any], *, observed_at: datetime | None = None) -> dict[str, Any]:
        if not isinstance(intent, dict):
            return {"ok": False, "status": "invalid_intent"}
        rows = [dict(row) for row in (self.observe() or ()) if isinstance(row, dict)]
        max_age = float(intent.get("maxAgeSeconds", intent.get("freshnessSeconds", 30)))
        if not math.isfinite(max_age) or max_age < 0:
            return {"ok": False, "status": "invalid_freshness"}
        cutoff = observed_at or _now()
        fresh = []
        for row in rows:
            stamp = _timestamp(row.get("observedAt") or row.get("timestamp"))
            if stamp is None or stamp > cutoff or (cutoff - stamp).total_seconds() > max_age:
                continue
            fresh.append(row)
        forbidden = {str(v) for v in (intent.get("forbiddenNeighbors") or [])}
        def safe_neighbor(row: dict[str, Any]) -> bool:
            neighbors = row.get("neighbors") or row.get("neighborIds") or []
            if isinstance(neighbors, dict):
                neighbors = neighbors.keys()
            return not forbidden.intersection({str(value) for value in neighbors})
        candidates = [row for row in fresh if _matches(row, intent) and _identity(row) not in forbidden and safe_neighbor(row)]
        if not candidates:
            return {"ok": False, "status": "target_not_found", "observedCount": len(fresh)}
        if len(candidates) != 1:
            return {"ok": False, "status": "ambiguous_target", "candidateIds": [_identity(row) for row in candidates]}
        target = candidates[0]
        if not _identity(target):
            return {"ok": False, "status": "target_identity_missing"}
        return {"ok": True, "status": "resolved", "target": target,
                "observedAt": target.get("observedAt") or target.get("timestamp")}

    def execute(self, intent: dict[str, Any], *, operation_id: str | None = None,
                authority: Any = None) -> dict[str, Any]:
        if not isinstance(authority, dict) or authority.get("granted") is not True:
            return {"ok": False, "status": "authority_required"}
        resolved = self.resolve(intent)
        if not resolved.get("ok"):
            return resolved
        target = resolved["target"]
        expected_transition = intent.get("expectedTransition") or intent.get("postcondition")
        if not expected_transition:
            return {"ok": False, "status": "postcondition_required"}
        if isinstance(expected_transition, dict) and "from" in expected_transition:
            if target.get(str(expected_transition.get("field") or "state")) != expected_transition["from"]:
                return {"ok": False, "status": "precondition_failed"}
        payload = {"intent": intent, "target": target, "targetId": _identity(target),
                   "action": intent.get("action") or "click"}

        def effect(_: dict[str, Any]) -> Any:
            return self.gateway(payload)

        def after(_: dict[str, Any]) -> Any:
            rows = [dict(row) for row in (self.observe() or ()) if isinstance(row, dict)]
            return {"identities": rows, "target": next((row for row in rows if _identity(row) == _identity(target)), None), "observedAt": _now().isoformat()}

        def verify(ctx: dict[str, Any]) -> dict[str, Any]:
            post = ctx.get("after") or {}
            post_target = post.get("target") if isinstance(post, dict) else None
            expected = intent.get("expectedTransition") or intent.get("postcondition")
            if not expected or not post_target or _timestamp(post.get("observedAt")) is None:
                return {"verified": False, "targetId": _identity(target), "reason": "post-observation or postcondition missing"}
            before_stamp = _timestamp(resolved.get("observedAt")); post_stamp = _timestamp(post_target.get("observedAt") or post_target.get("timestamp"))
            if not post_stamp or post_stamp > _now() or (before_stamp and post_stamp <= before_stamp):
                return {"verified": False, "targetId": _identity(target), "reason": "post-observation is not newer"}
            if callable(expected):
                passed = bool(expected(post_target, ctx.get("effect")))
            elif isinstance(expected, dict):
                if "from" in expected or "to" in expected:
                    destination = expected.get("to")
                    key = str(expected.get("field") or "state")
                    passed = post_target.get(key) == destination
                else:
                    passed = all(post_target.get(k) == v for k, v in expected.items())
            elif isinstance(expected, str):
                passed = bool(post_target) and str(post_target.get("state") or post_target.get("status") or "") == expected
            else:
                passed = bool(post_target)
            return {"verified": passed, "targetId": _identity(target),
                    "reason": "postcondition matched" if passed else "expected transition not observed"}

        if self.verified_store and operation_id:
            result = self.verified_store.execute(operation_id, str(intent.get("action") or "intent.action"),
                                                 authority=authority, before=lambda _: resolved,
                                                 effect=effect, after=after, verify=verify,
                                                 recovery_ref=intent.get("recoveryRef"),
                                                 request={"intent": intent, "targetId": _identity(target)})
            return {**result, "resolution": resolved}
        try:
            effect_result = self.gateway(payload)
            post = after({})
            verification = verify({"effect": effect_result, "after": post})
            if isinstance(effect_result, dict) and (effect_result.get("ok") is False or effect_result.get("status") in {"failed", "blocked", "unknown_side_effects"}):
                verification = {"verified": False, "reason": "action did not succeed"}
            return {"ok": bool(verification.get("verified")),
                    "status": "verified" if verification.get("verified") else "postcondition_failed",
                    "resolution": resolved, "effect": effect_result, "after": post,
                    "verification": verification}
        except Exception as exc:
            return {"ok": False, "status": "unknown_side_effects", "resolution": resolved,
                    "message": "Action outcome is unknown; do not retry automatically.", "error": str(exc)}


SemanticIntentAction = IntentAction
