"""Usage receipts: context size and cumulative thread spend are different facts."""
from __future__ import annotations

FIELDS = ("inputTokens", "outputTokens", "cachedInputTokens", "totalTokens")


def counters(value):
    if not isinstance(value, dict):
        return None
    result = {key: value.get(key) for key in FIELDS}
    if not all(isinstance(result[key], int) and not isinstance(result[key], bool) and result[key] >= 0
               for key in ("inputTokens", "outputTokens")):
        return None
    result["totalTokens"] = result["inputTokens"] + result["outputTokens"]
    if not isinstance(result["cachedInputTokens"], int) or isinstance(result["cachedInputTokens"], bool):
        result["cachedInputTokens"] = None
    return result


class CodexUsage:
    def __init__(self, baseline=None):
        self.baseline = counters(baseline)
        self.total = None
        self.updates = 0

    def observe(self, total):
        value = counters(total)
        if value is None or value == self.total:
            return False
        # A reset is not negative spending. Keep totals, but stop claiming a delta.
        if self.total and any(value[key] < self.total[key] for key in ("inputTokens", "outputTokens")):
            self.baseline = None
        self.total = value
        self.updates += 1
        return True

    def receipt(self):
        if self.total is None:
            return None
        known = self.baseline is not None and all(self.total[key] >= self.baseline[key]
                                                   for key in ("inputTokens", "outputTokens"))
        delta = {key: (self.total[key] - self.baseline[key]
                      if known and self.total[key] is not None and self.baseline[key] is not None else None)
                 for key in FIELDS}
        return {**delta, "requests": None, "usageUpdates": self.updates,
                "threadTotal": self.total, "reportedByTransport": known,
                "coverage": "reported" if known else "thread_total_only"}


ZERO = dict.fromkeys(FIELDS, 0)


def runtime_usage(result):
    if result.get("runtime") == "neyvia-agent" and isinstance(result.get("raw"), dict):
        return result["raw"].get("usage")
    return None


def record_run_usage(run, event):
    tracker = run.usage_tracker
    if isinstance(event.get("usage"), dict):
        if run.data.get("usage") == event["usage"]:
            return False
        run.data["usage"] = event["usage"]
        return True
    if event["type"] == "usage.baseline":
        if tracker.total is None:
            tracker.baseline = counters(event.get("threadTotal"))
        return False
    if not tracker.observe(event.get("threadTotal")):
        return False
    run.data["usage"] = tracker.receipt()
    return True


def sdk_receipt(usage):
    details = getattr(usage, "input_tokens_details", None)
    if not getattr(usage, "total_tokens", 0):
        return {"requests": getattr(usage, "requests", None), **dict.fromkeys(FIELDS)}
    return {"requests": getattr(usage, "requests", None),
            "inputTokens": getattr(usage, "input_tokens", None),
            "outputTokens": getattr(usage, "output_tokens", None),
            "totalTokens": getattr(usage, "total_tokens", None),
            "cachedInputTokens": getattr(details, "cached_tokens", None)}


def claude_receipt(usage):
    if not isinstance(usage, dict):
        return None
    keys = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    if not all(isinstance(usage.get(key), int) and not isinstance(usage[key], bool) and usage[key] >= 0 for key in keys):
        return None
    input_tokens = sum(usage[key] for key in keys if key != "output_tokens")
    return {"inputTokens": input_tokens, "outputTokens": usage["output_tokens"],
            "cachedInputTokens": usage["cache_read_input_tokens"],
            "cacheCreationInputTokens": usage["cache_creation_input_tokens"],
            "totalTokens": input_tokens + usage["output_tokens"], "requests": None,
            "coverage": "reported", "reportedByTransport": True}


def add_summary_usage(compactor, usage):
    """Count every attempted summary, including rejected formats and failures."""
    receipt = sdk_receipt(usage) if usage is not None else dict.fromkeys(("requests", *FIELDS))
    ledger = compactor.stats.setdefault("usage", {"requests": 0, **ZERO, "unknownCalls": 0})
    ledger["requests"] += receipt.get("requests") or 1
    if usage is None or not receipt.get("requests"):
        ledger["unknownCalls"] += 1
    for key in FIELDS:
        if receipt.get(key) is None or ledger.get(key) is None:
            ledger[key] = None
        else:
            ledger[key] += receipt[key]


def include_compaction(usage, compactor):
    summary = compactor.stats.get("usage") if compactor else None
    if not summary:
        return usage
    result = dict(usage)
    result["stages"] = {"execution": dict(usage), "compaction": dict(summary)}
    for key in ("requests", *FIELDS):
        result[key] = usage[key] + summary[key] if usage.get(key) is not None and summary.get(key) is not None else None
    result["reportedByTransport"] = bool(usage.get("reportedByTransport") and not summary["unknownCalls"])
    return result


def stream_sdk_usage(contract, usage):
    current = sdk_receipt(usage)
    previous = getattr(contract, "completed_usage", {"requests": 0, **ZERO})
    result = {key: current[key] + previous[key] if current.get(key) is not None and previous.get(key) is not None else None
              for key in ("requests", *FIELDS)}
    result["reportedByTransport"] = current.get("totalTokens") is not None and previous.get("totalTokens") is not None
    contract.live_usage = result
    return include_compaction(result, contract.compactor)


def accumulate_sdk_usage(accumulated, usage, requests):
    receipt = sdk_receipt(usage)
    for key in FIELDS:
        accumulated[key] = (accumulated[key] + receipt[key]
                            if accumulated.get(key) is not None and receipt.get(key) is not None else None)
    accumulated["requests"] += requests
    accumulated["reportedByTransport"] = accumulated["totalTokens"] is not None
