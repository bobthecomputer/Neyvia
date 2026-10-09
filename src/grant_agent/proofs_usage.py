"""Pure cases for the Usage endpoint contracts (usage.endpoint.shape, usage.plan.api-equivalent-only): no scan, process or network."""
from __future__ import annotations

import copy

from .usage_report import api_equivalent, base_model, check_report

CONTRACT = "usage.endpoint.shape"
RULE = "usage.plan.api-equivalent-only"


def _good() -> dict:
    days = [{"day": f"2026-10-0{n}", "agents": {"claude-code": {"input": 10, "cached": 8, "output": 2}}} for n in range(1, 8)]
    return {
        "ok": True, "range": "week", "days": 7, "generatedAt": "2026-10-08T10:00:00+00:00", "scan": {"active": False}, "windowDays": 31,
        "plans": [{"app": "codex", "window": "weekly", "usedPercent": 52.0, "resetsAt": "2026-10-14T03:29:06Z"}], "providers": [],
        "totals": {"input": 70, "cached": 56, "output": 14, "cacheShare": 0.8}, "byDay": days,
        "rows": [
            {"agent": "claude-code", "provider": "anthropic", "model": "claude-opus-5-5", "billing": "plan", "input": 40, "cached": 30, "cacheWrite": 5, "output": 8,
             "cacheShare": 0.75, "apiEquivUsd": 2.0, "billedUsd": None},
            {"agent": "opencode", "provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "billing": "api", "input": 30, "cached": 26, "cacheWrite": 0, "output": 6,
             "cacheShare": 0.87, "apiEquivUsd": 0.5, "billedUsd": 0.5},
        ],
        "cost": {"estimate": True, "pricesChecked": "2026-10-08", "apiEquivalentTotalUsd": 2.5, "billedTotalUsd": 0.5},
        "savings": {"cacheShare": 0.8},
    }


def _refused(mutate) -> bool:
    report = copy.deepcopy(_good())
    mutate(report)
    try:
        check_report(report)
    except ValueError:
        return True
    return False


def _check_report_outcomes() -> dict:
    check_report(_good())
    cases = {
        "plan traffic shown as billed": lambda r: r["rows"][0].update(billedUsd=2.0),
        "unknown billing shown as billed": lambda r: r["rows"][0].update(billing="unknown", billedUsd=2.0),
        "key traffic billed at another price": lambda r: r["rows"][1].update(billedUsd=9.0),
        "billed total without key traffic": lambda r: r["rows"].pop(1),
        "billed total that is not the sum of key rows": lambda r: r["cost"].update(billedTotalUsd=7.0),
        "equivalent total that is not the sum of rows": lambda r: r["cost"].update(apiEquivalentTotalUsd=90.0),
        "cost not flagged as estimate": lambda r: r["cost"].update(estimate=False),
        "cost without a price date": lambda r: r["cost"].update(pricesChecked=None),
        "missing section": lambda r: r.pop("byDay"),
        "days not matching the range": lambda r: r["byDay"].pop(),
        "cached and written above input": lambda r: r["rows"][1].update(cached=99),
        "plan percent over 100": lambda r: r["plans"][0].update(usedPercent=130),
    }
    missed = [name for name, mutate in cases.items() if not _refused(mutate)]
    if missed:
        raise AssertionError(f"{CONTRACT}: the report check let through: {', '.join(missed)}")
    # Pricing arithmetic: each kind of token at its own rate, an unknown model stays unpriced, spelling does not matter.
    prices = {"models": {"m": {"input": 10.0, "cached": 1.0, "cacheWrite": 12.5, "cacheWrite1h": 20.0, "output": 50.0, "aliases": ["m-alias"]}}}
    parts = api_equivalent("vendor/M-alias-20260101", 1_000_000, 400_000, 100_000, 100_000, 100_000, prices)
    expected = {"input": 4.0 * 1.0 + 0.0, "cached": 0.4, "cacheWrite": 1.25 + 2.0, "output": 5.0}
    # fresh = 1,000,000 - 400,000 - 100,000 - 100,000 = 400,000 tokens at 10 per million = 4.0
    if parts is None or any(abs(parts[key] - value) > 1e-9 for key, value in expected.items()) or abs(parts["total"] - 12.65) > 1e-9:
        raise AssertionError(f"{RULE}: API-equivalent arithmetic changed: {parts}")
    if api_equivalent("no-such-model", 1, 0, 1, 0, 0, prices) is not None or base_model("~anthropic/Claude-Opus-5-5-20260101[1m]") != "claude-opus-5-5":
        raise AssertionError(f"{RULE}: an unknown model must stay unpriced and spellings must normalise")
    return {"contract": [CONTRACT, RULE], "refused": sorted(cases)}


def self_check(scratch=None) -> dict:
    from .contract_gate import wants
    observed = _check_report_outcomes()
    cases = [{"id": identity, "contracts": [identity], "ok": True, "observed": observed}
             for identity in (CONTRACT, RULE) if wants(identity)]
    return {"ok": bool(cases), "cases": cases, "contracts": [row["id"] for row in cases]}
