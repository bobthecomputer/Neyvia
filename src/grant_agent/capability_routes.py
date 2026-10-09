"""Constraint-aware model and harness capability routing.

This module is deliberately registry-shaped: callers can pass rows from
``model_portfolio`` or ``harness_registry`` without coupling the runtime to a
specific registry implementation.  Requested routes and observed routes are
kept as separate values; a request is never promoted to evidence by inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


SCHEMA = "neyvia.capability_route.v1"
_EFFORT_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "xhigh": 4, "max": 5}


def _text(value: object) -> str:
    return str(value or "").strip()


def _strings(value: object) -> frozenset[str]:
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if not isinstance(value, Iterable):
        return frozenset()
    result: set[str] = set()
    for item in value:
        if isinstance(item, Mapping):
            item = item.get("key") or item.get("id") or item.get("name") or item.get("capability") or item.get("tool")
        text = _text(item).lower()
        if text:
            result.add(text)
    return frozenset(result)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class CapabilityRequirement:
    """The contract a route must satisfy before it can be selected."""

    capabilities: frozenset[str] = frozenset()
    minimum_effort: str = "none"
    tools: frozenset[str] = frozenset()
    minimum_context_tokens: int = 0
    privacy_boundary: str = ""
    budget: Mapping[str, float] = field(default_factory=dict)
    preferred_route_id: str = ""

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any] | None) -> "CapabilityRequirement":
        data = payload or {}
        return cls(
            capabilities=_strings(data.get("capabilities") or data.get("requiredCapabilities")),
            minimum_effort=_text(data.get("minimumEffort") or data.get("effort") or "none").lower(),
            tools=_strings(data.get("tools") or data.get("requiredTools")),
            minimum_context_tokens=max(0, int(data.get("minimumContextTokens") or data.get("contextTokens") or 0)),
            privacy_boundary=_text(data.get("privacyBoundary") or data.get("privacy") or "").lower(),
            budget=dict(data.get("budget") or {}),
            preferred_route_id=_text(data.get("preferredRouteId") or data.get("routeId")),
        )


@dataclass(frozen=True)
class RouteCandidate:
    route_id: str
    provider: str
    runtime: str
    model: str
    effort: str
    capabilities: frozenset[str] = frozenset()
    tools: frozenset[str] = frozenset()
    context_tokens: int = 0
    privacy_boundary: str = ""
    budget: Mapping[str, float] = field(default_factory=dict)
    available: bool = True
    source: str = "registry"
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "RouteCandidate":
        data = dict(payload)
        availability = data.get("availability") if isinstance(data.get("availability"), Mapping) else {}
        capabilities = data.get("capabilities") or data.get("requiredCapabilities") or data.get("supports")
        tools = data.get("tools") or data.get("toolCompatibility") or data.get("supportedTools")
        return cls(
            route_id=_text(data.get("routeId") or data.get("id") or data.get("route_id")),
            provider=_text(data.get("provider") or data.get("providerId")),
            runtime=_text(data.get("runtime") or data.get("runtimeId") or data.get("harnessId")),
            model=_text(data.get("model")),
            effort=_text(data.get("effort") or data.get("defaultReasoningEffort") or "none").lower(),
            capabilities=_strings(capabilities),
            tools=_strings(tools),
            context_tokens=max(0, int(data.get("contextTokens") or data.get("context_tokens") or 0)),
            privacy_boundary=_text(data.get("privacyBoundary") or data.get("privacy") or "").lower(),
            budget=dict(data.get("budget") or {}),
            available=bool(data.get("available", availability.get("ready", True))),
            source=_text(data.get("source") or "registry"),
            raw=data,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "routeId": self.route_id, "provider": self.provider, "runtime": self.runtime,
            "model": self.model, "effort": self.effort, "capabilities": sorted(self.capabilities),
            "tools": sorted(self.tools), "contextTokens": self.context_tokens,
            "privacyBoundary": self.privacy_boundary, "budget": dict(self.budget),
            "available": self.available, "source": self.source,
        }


@dataclass(frozen=True)
class ObservedRouteEvidence:
    """Evidence emitted by the actual harness/provider invocation."""

    route_id: str
    provider: str
    runtime: str
    model: str
    effort: str = ""
    observed_at: str = field(default_factory=_now)
    evidence_id: str = ""
    source: str = "runtime"

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ObservedRouteEvidence":
        return cls(
            route_id=_text(payload.get("routeId") or payload.get("route_id")),
            provider=_text(payload.get("provider") or payload.get("providerId")),
            runtime=_text(payload.get("runtime") or payload.get("runtimeId") or payload.get("harnessId")),
            model=_text(payload.get("model")), effort=_text(payload.get("effort")).lower(),
            observed_at=_text(payload.get("observedAt") or payload.get("observed_at") or _now()),
            evidence_id=_text(payload.get("evidenceId") or payload.get("receiptId")),
            source=_text(payload.get("source") or "runtime"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {"routeId": self.route_id, "provider": self.provider, "runtime": self.runtime,
                "model": self.model, "effort": self.effort, "observedAt": self.observed_at,
                "evidenceId": self.evidence_id, "source": self.source}


def _reasons(route: RouteCandidate, req: CapabilityRequirement) -> list[str]:
    reasons: list[str] = []
    if not route.available: reasons.append("route_unavailable")
    if not req.capabilities.issubset(route.capabilities): reasons.append("missing_capability")
    if _EFFORT_ORDER.get(route.effort, -1) < _EFFORT_ORDER.get(req.minimum_effort, 0): reasons.append("insufficient_effort")
    if not req.tools.issubset(route.tools): reasons.append("tool_incompatible")
    if route.context_tokens and route.context_tokens < req.minimum_context_tokens: reasons.append("insufficient_context")
    elif req.minimum_context_tokens and not route.context_tokens: reasons.append("context_unverified")
    if req.privacy_boundary and route.privacy_boundary != req.privacy_boundary: reasons.append("privacy_boundary_mismatch")
    for key, limit in req.budget.items():
        actual = route.budget.get(key)
        if actual is None: reasons.append(f"budget_{key}_unverified")
        elif float(actual) > float(limit): reasons.append(f"budget_{key}_exceeded")
    return reasons


def route_capability(
    candidates: Iterable[Mapping[str, Any] | RouteCandidate],
    requirement: CapabilityRequirement | Mapping[str, Any],
    *,
    fallback_authorized: bool = False,
    observed: ObservedRouteEvidence | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Select a route only when its constraints are proven by registry data.

    ``fallback_authorized`` is explicit.  Observed evidence is optional and is
    never synthesized from the requested candidate.
    """
    req = requirement if isinstance(requirement, CapabilityRequirement) else CapabilityRequirement.from_payload(requirement)
    rows = [row if isinstance(row, RouteCandidate) else RouteCandidate.from_payload(row) for row in candidates]
    eligible = [row for row in rows if not _reasons(row, req)]
    preferred = next((row for row in eligible if req.preferred_route_id and row.route_id == req.preferred_route_id), None)
    selected = preferred or (eligible[0] if eligible else None)
    fallback_used = bool(selected and req.preferred_route_id and selected.route_id != req.preferred_route_id)
    if fallback_used and not fallback_authorized:
        selected = None
    evidence = observed if isinstance(observed, ObservedRouteEvidence) else (ObservedRouteEvidence.from_payload(observed) if observed else None)
    evidence_status = "unobserved"
    if evidence and selected:
        evidence_status = "observed" if (evidence.route_id == selected.route_id and evidence.model == selected.model) else "mismatch"
    elif evidence:
        evidence_status = "observed_without_selection"
    return {
        "schema": SCHEMA,
        "status": "selected" if selected else "blocked",
        "selectedRoute": selected.as_dict() if selected else None,
        "requestedRouteId": req.preferred_route_id,
        "fallback": {"authorized": bool(fallback_authorized), "used": fallback_used},
        "rejections": {row.route_id: _reasons(row, req) for row in rows if _reasons(row, req)},
        "routeEvidence": evidence.as_dict() if evidence else None,
        "evidenceStatus": evidence_status,
        "proof": "requested route is not runtime evidence; provide observed evidence after invocation",
    }


def select_capability_route(
    candidates: Iterable[Mapping[str, Any] | RouteCandidate],
    requirement: CapabilityRequirement | Mapping[str, Any],
    *,
    fallback_authorized: bool = False,
    observed: ObservedRouteEvidence | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Readable runtime alias for :func:`route_capability`."""
    return route_capability(
        candidates,
        requirement,
        fallback_authorized=fallback_authorized,
        observed=observed,
    )
