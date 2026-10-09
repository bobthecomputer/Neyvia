"""Provider-neutral task lanes for Neyvia model routing.

The portfolio separates task intent from provider identity.  A lane can expose
several honest route candidates, but Neyvia never silently substitutes one
provider for another.  The operator chooses or confirms the route that will
actually run.
"""

from __future__ import annotations

from .proofs_c_models import checked

import re
from typing import Any


MODEL_PORTFOLIO_SCHEMA = "neyvia.model_portfolio.v1"
MODEL_PORTFOLIO_SOURCE_CHECKED_AT = "2026-07-30"

KIMI_CODE_MODEL_CONTRACT = {
    "k3": {
        "contextTokens": 1_048_576,
        "contextQualification": "up_to_by_membership",
        "taskClass": "deep",
        "efforts": ("low", "high", "max"),
    },
    "k3-256k": {
        "contextTokens": 262_144,
        "contextQualification": "fixed",
        "taskClass": "routine",
        "efforts": ("low", "high", "max"),
    },
    "kimi-for-coding": {
        "contextTokens": 262_144,
        "contextQualification": "fixed",
        "taskClass": "routine",
        "efforts": (),
    },
    "kimi-for-coding-highspeed": {
        "contextTokens": 262_144,
        "contextQualification": "fixed",
        "taskClass": "latency",
        "efforts": (),
    },
}


def _availability(
    *,
    provider_id: str,
    provider_presence: dict[str, bool],
    runtime_id: str,
    runtime_presence: dict[str, bool],
    managed_auth_may_be_ambient: bool = False,
    configuration_observed: bool | None = None,
) -> dict[str, Any]:
    runner_available = bool(runtime_presence.get(runtime_id))
    auth_observed = bool(provider_presence.get(provider_id))
    if (
        runner_available
        and auth_observed
        and configuration_observed is False
    ):
        state = "provider_profile_required"
        detail = (
            "The runner and credential are present, but a provider profile with "
            "an explicit base URL and model contract is still required."
        )
    elif runner_available and auth_observed:
        state = "ready"
        detail = "Runner and provider authentication were both observed."
    elif runner_available and managed_auth_may_be_ambient:
        state = "runner_ready_auth_unchecked"
        detail = (
            "The runner is installed. Managed account authentication must be "
            "proved by a live provider response."
        )
    elif not runner_available:
        state = "runner_required"
        detail = f"The {runtime_id} runner was not detected."
    else:
        state = "authentication_required"
        detail = f"Connect {provider_id} before this route can be called ready."
    return {
        "state": state,
        "ready": state == "ready",
        "runnerAvailable": runner_available,
        "authObserved": auth_observed,
        "authChecked": auth_observed or not managed_auth_may_be_ambient,
        "configurationObserved": configuration_observed,
        "detail": detail,
    }


def _route(
    route_id: str,
    *,
    provider: str,
    runtime: str,
    model: str,
    effort: str,
    task_class: str,
    context_tokens: int,
    context_qualification: str,
    availability: dict[str, Any],
    source: str,
    note: str,
) -> dict[str, Any]:
    return {
        "routeId": route_id,
        "provider": provider,
        "runtime": runtime,
        "model": model,
        "effort": effort,
        "taskClass": task_class,
        "contextTokens": context_tokens,
        "contextQualification": context_qualification,
        "availability": availability,
        "source": source,
        "note": note,
        "fallbackAllowed": False,
        "operatorConfirmationRequired": True,
    }


def _lane(
    lane_id: str,
    *,
    label: str,
    description: str,
    routes: list[dict[str, Any]],
) -> dict[str, Any]:
    ready_route = next(
        (route for route in routes if route["availability"]["ready"]),
        None,
    )
    recommended = ready_route or (routes[0] if routes else None)
    return {
        "laneId": lane_id,
        "label": label,
        "description": description,
        "selectionState": "ready" if ready_route else "setup_required",
        "recommendedRouteId": (
            str(recommended.get("routeId") or "") if recommended else ""
        ),
        "routes": routes,
        "routeCount": len(routes),
        "readyRouteCount": sum(
            1 for route in routes if route["availability"]["ready"]
        ),
    }


@checked("portfolio")
def build_model_portfolio(
    *,
    provider_presence: dict[str, bool] | None = None,
    runtime_presence: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build the task-first route portfolio without inferring authentication."""

    providers = dict(provider_presence or {})
    runtimes = dict(runtime_presence or {})
    kimi_runner = _availability(
        provider_id="kimi-code",
        provider_presence=providers,
        runtime_id="kimi-code",
        runtime_presence=runtimes,
        managed_auth_may_be_ambient=True,
        configuration_observed=bool(runtimes.get("kimi-code-profile")),
    )
    codex_runner = _availability(
        provider_id="openai-codex",
        provider_presence=providers,
        runtime_id="codex",
        runtime_presence=runtimes,
    )
    opencode_go_runner = _availability(
        provider_id="opencode-go",
        provider_presence=providers,
        runtime_id="opencode",
        runtime_presence=runtimes,
    )

    routine_routes = [
        _route(
            "kimi-code:k3-256k:low",
            provider="kimi-code",
            runtime="kimi-code",
            model="k3-256k",
            effort="low",
            task_class="routine",
            context_tokens=262_144,
            context_qualification="fixed",
            availability=kimi_runner,
            source="https://www.kimi.com/code/docs/en/kimi-code/models.html",
            note=(
                "Kimi Code's quota-efficient K3 lane for everyday work, code "
                "completion, and single-file or small-file changes."
            ),
        ),
        _route(
            "openai-codex:gpt-5.6-sol:low",
            provider="openai-codex",
            runtime="codex",
            model="gpt-5.6-sol",
            effort="low",
            task_class="routine",
            context_tokens=0,
            context_qualification="provider_reported_at_runtime",
            availability=codex_runner,
            source="neyvia.current_codex_contract",
            note="Keep the already configured Codex model available for bounded work.",
        ),
        _route(
            "opencode-go:kimi-k3:low",
            provider="opencode-go",
            runtime="opencode",
            model="kimi-k3",
            effort="low",
            task_class="routine",
            context_tokens=0,
            context_qualification="provider_reported_at_runtime",
            availability=opencode_go_runner,
            source="https://opencode.ai/docs/go/",
            note=(
                "OpenCode Go exposes the provider-specific `kimi-k3` identifier. "
                "It is not interchangeable with the Kimi Code `k3` alias."
            ),
        ),
    ]
    deep_routes = [
        _route(
            "kimi-code:k3:high",
            provider="kimi-code",
            runtime="kimi-code",
            model="k3",
            effort="high",
            task_class="deep",
            context_tokens=1_048_576,
            context_qualification="up_to_by_membership",
            availability=kimi_runner,
            source="https://www.kimi.com/code/docs/en/kimi-code/models.html",
            note=(
                "Kimi Code K3 for large codebases, multi-file refactors, and long "
                "documents. The 1M window depends on membership."
            ),
        ),
        _route(
            "openai-codex:gpt-5.6-sol:high",
            provider="openai-codex",
            runtime="codex",
            model="gpt-5.6-sol",
            effort="high",
            task_class="deep",
            context_tokens=0,
            context_qualification="provider_reported_at_runtime",
            availability=codex_runner,
            source="neyvia.current_codex_contract",
            note="The existing proven route remains available for sustained work.",
        ),
        _route(
            "opencode-go:kimi-k3:high",
            provider="opencode-go",
            runtime="opencode",
            model="kimi-k3",
            effort="high",
            task_class="deep",
            context_tokens=0,
            context_qualification="provider_reported_at_runtime",
            availability=opencode_go_runner,
            source="https://opencode.ai/docs/go/",
            note="Provider-brokered Kimi K3 through the current OpenCode Go model ID.",
        ),
    ]
    verification_routes = [
        _route(
            "openai-codex:gpt-5.6-sol:high:verify",
            provider="openai-codex",
            runtime="codex",
            model="gpt-5.6-sol",
            effort="high",
            task_class="verification",
            context_tokens=0,
            context_qualification="provider_reported_at_runtime",
            availability=codex_runner,
            source="neyvia.current_codex_contract",
            note="Independent verification keeps its own receipt and authority boundary.",
        ),
        _route(
            "opencode-go:kimi-k3:high:verify",
            provider="opencode-go",
            runtime="opencode",
            model="kimi-k3",
            effort="high",
            task_class="verification",
            context_tokens=0,
            context_qualification="provider_reported_at_runtime",
            availability=opencode_go_runner,
            source="https://opencode.ai/docs/go/",
            note="Optional independent Kimi verifier when OpenCode Go is authenticated.",
        ),
    ]

    lanes = [
        _lane(
            "routine",
            label="Routine",
            description=(
                "Small, reversible, bounded work with an efficient context and "
                "reasoning budget."
            ),
            routes=routine_routes,
        ),
        _lane(
            "deep",
            label="Deep",
            description=(
                "Large-context analysis, multi-file changes, architecture, and "
                "long-running synthesis."
            ),
            routes=deep_routes,
        ),
        _lane(
            "verification",
            label="Verify",
            description=(
                "A separately receipted review lane. It never inherits the "
                "executor's claim of success."
            ),
            routes=verification_routes,
        ),
    ]
    return {
        "schema": MODEL_PORTFOLIO_SCHEMA,
        "sourceCheckedAt": MODEL_PORTFOLIO_SOURCE_CHECKED_AT,
        "selectionPolicy": "task_first_operator_confirmed",
        "autoFallback": False,
        "cachePolicy": (
            "Start a new model session when changing Kimi model or reasoning "
            "effort so a stale prompt cache is not misreported as efficient reuse."
        ),
        "modelIdentifierContract": {
            "kimiCodeAliases": list(KIMI_CODE_MODEL_CONTRACT),
            "kimiOpenPlatformId": "kimi-k3",
            "openCodeGoId": "kimi-k3",
            "aliasesInterchangeable": False,
        },
        "lanes": lanes,
        "summary": {
            "laneCount": len(lanes),
            "routeCount": sum(len(lane["routes"]) for lane in lanes),
            "readyRouteCount": sum(
                lane["readyRouteCount"] for lane in lanes
            ),
            "authUncheckedRouteCount": sum(
                1
                for lane in lanes
                for route in lane["routes"]
                if route["availability"]["state"]
                == "runner_ready_auth_unchecked"
            ),
        },
    }


@checked("classification")
def classify_task_lane(value: object, *, fallback: str = "routine") -> str:
    """Classify a plain-language task without selecting a provider."""

    text = re.sub(r"\s+", " ", str(value or "").strip().casefold())
    if not text:
        return fallback
    if re.search(
        r"\b(?:verify|verification|review|audit|prove|proof|acceptance)\b",
        text,
    ):
        return "verification"
    if re.search(
        r"\b(?:architecture|deep|large codebase|long context|multi[- ]file|"
        r"migration|redesign|system[- ]wide|whole repo|entire repo)\b",
        text,
    ):
        return "deep"
    if re.search(
        r"\b(?:small|little|quick|routine|single[- ]file|bounded|typo|"
        r"rename|format|summari[sz]e)\b",
        text,
    ):
        return "routine"
    return fallback


def recommended_route(
    portfolio: dict[str, Any],
    lane_id: str,
) -> dict[str, Any] | None:
    """Return the stated recommendation without performing a fallback."""

    for lane in portfolio.get("lanes") or []:
        if not isinstance(lane, dict) or lane.get("laneId") != lane_id:
            continue
        route_id = str(lane.get("recommendedRouteId") or "")
        for route in lane.get("routes") or []:
            if isinstance(route, dict) and route.get("routeId") == route_id:
                return dict(route)
    return None
