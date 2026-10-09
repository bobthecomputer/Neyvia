"""Route-specific context admission. Pricing never silently becomes a stop budget."""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path


def estimate_tokens(value):
    """Conservative text estimate, explicitly not a model tokenizer.

    Non-ASCII bytes are counted separately so a CJK/emoji payload cannot inherit
    an English characters-per-token assumption. Provider usage replaces the
    estimate for an unchanged prefix once it is available.
    """
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    ascii_count = sum(ord(c) < 128 for c in text)
    return math.ceil(ascii_count / 3) + len(text.encode("utf-8")) - ascii_count + 8


def _positive(value):
    return value if type(value) is int and value > 0 else None


def _read(path):
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def price_threshold(cost):
    """Use explicit tier sizes, never infer 200K from a legacy alias key."""
    thresholds = []
    for row in cost.get("tiers", []):
        if not isinstance(row, dict):
            continue
        tier = row.get("tier", {})
        size = _positive(tier.get("size")) if isinstance(tier, dict) else None
        if not size or tier.get("type") != "context":
            continue
        if any(type(row.get(key)) in (int, float) and type(cost.get(key)) in (int, float)
               and row[key] > cost[key] for key in ("input", "output", "cache_read", "cache_write")):
            thresholds.append(size)
    return min(thresholds, default=None)


@dataclass
class CompactionPolicy:
    route: str
    context_tokens: int
    input_limit: int
    output_reserve: int
    mode: str = "capacity"
    price_tier: int | None = None
    source: str = "unknown-model-conservative-fallback"
    fetched_at: str = ""

    @property
    def capacity_trigger(self):
        return max(1, min(int(self.context_tokens * .85), self.input_limit,
                          self.context_tokens - self.output_reserve))

    @property
    def trigger(self):
        if self.mode == "avoid-price-increase" and self.price_tier:
            return min(self.capacity_trigger, int(self.price_tier * .90))
        return self.capacity_trigger

    @property
    def target(self):
        # Leave useful room for further tool rounds instead of compacting again
        # after the very next result. This is a token target, not a record count.
        return int(self.trigger * .65)

    def receipt(self):
        return {"route": self.route, "mode": self.mode, "contextTokens": self.context_tokens,
                "inputLimitTokens": self.input_limit, "outputReserveTokens": self.output_reserve,
                "triggerTokens": self.trigger, "targetTokens": self.target,
                "priceTierTokens": self.price_tier, "metadataSource": self.source,
                "metadataFetchedAt": self.fetched_at,
                "reason": "price_tier" if self.trigger < self.capacity_trigger else "context_capacity",
                "tokenMeasurement": "estimated; provider-measured unchanged prefix when available"}


def resolve_policy(root: Path, provider: str, model: str, max_output_tokens=None):
    route = f"{provider}/{model}"
    cache = _read(root / ".agent_control/provider_model_catalog.modelsdev.json")
    raw = cache.get("catalog", {}).get(provider, {}).get("models", {}).get(model, {})
    catalog_root = Path(os.environ.get("NEYVIA_CONTEXT_CATALOG_ROOT") or root)
    if not raw and catalog_root != root:
        cache = _read(catalog_root / ".agent_control/provider_model_catalog.modelsdev.json")
        raw = cache.get("catalog", {}).get(provider, {}).get("models", {}).get(model, {})
    source = "models.dev-cache" if raw else "unknown-model-conservative-fallback"
    # A documented bootstrap for the current route; no cross-provider pricing
    # inference. Other routes use discovered metadata or an explicit override.
    if not raw and provider in {"opencode-go", "deepseek"} and model in {"deepseek-v4.1-flash", "deepseek-flash", "deepseek-v4-pro"}:
        raw = {"limit": {"context": 1_000_000, "output": 384_000}}
        source = "documented-deepseek-context-2026-09-28"
    limits = raw.get("limit") if isinstance(raw.get("limit"), dict) else {}
    cost = raw.get("cost") if isinstance(raw.get("cost"), dict) else {}
    settings = _read(catalog_root / "config/neyvia_context_policy.json")
    if catalog_root != root:
        local = _read(root / "config/neyvia_context_policy.json")
        settings = {**settings, **local, "routes": {**settings.get("routes", {}), **local.get("routes", {})}}
    overrides = settings.get("routes", {}).get(route, {})
    context = _positive(overrides.get("contextTokens")) or _positive(limits.get("context")) or 32_768
    input_limit = min(context, _positive(overrides.get("inputLimitTokens")) or _positive(limits.get("input")) or context)
    # When the caller did not select an output budget, reserve and actually
    # send this maximum to the SDK. Reservation must match the request.
    reserve = max_output_tokens or min(_positive(limits.get("output")) or 16_000,
                                      max(4096, min(64_000, context // 10)))
    mode = overrides.get("mode", settings.get("mode", "capacity"))
    if mode not in {"capacity", "avoid-price-increase"}:
        raise ValueError("Compaction mode must be capacity or avoid-price-increase")
    if reserve >= context:
        raise ValueError("Output reservation must be smaller than the model context")
    return CompactionPolicy(route, context, input_limit, reserve, mode,
                            price_threshold(cost), source, str(cache.get("fetchedAt", "")))


class ContextMeter:
    """Measure the full prompt, with usage-backed prefix reuse and no text saved."""
    def __init__(self, instructions, tools):
        self.overhead = estimate_tokens({"instructions": instructions, "tools": tools})
        self.last = None
        self.pending = None

    def measure(self, items):
        rows = [json.dumps(x, ensure_ascii=False, sort_keys=True) for x in items]
        result = self.overhead + sum(estimate_tokens(x) for x in rows)
        if self.last and len(rows) >= self.last[0]:
            count, digest, actual = self.last
            if hashlib.sha256("\n".join(rows[:count]).encode()).hexdigest() == digest:
                result = actual + sum(estimate_tokens(x) for x in rows[count:])
        return result

    def sent(self, items):
        rows = [json.dumps(x, ensure_ascii=False, sort_keys=True) for x in items]
        self.pending = (len(rows), hashlib.sha256("\n".join(rows).encode()).hexdigest())

    def observe(self, input_tokens):
        if self.pending and _positive(input_tokens):
            self.last = (*self.pending, input_tokens)
        self.pending = None
