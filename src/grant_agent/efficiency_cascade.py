"""Validated script → transition memory → System 1 → cache → Luna → Sol routing.

Every accepted answer passes both its JSON schema and the caller's domain check.
Measured budgets are receipts, not promises. No unavailable provider is replaced.
"""
from __future__ import annotations

import math
import platform
import json
import os
import re
import subprocess
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .transition_memory import TransitionStore, atomic_json, canonical, digest, locked, read_json
from .subprocess_utils import hidden_windows_subprocess_kwargs


class CascadeError(RuntimeError):
    def __init__(self, message: str, receipt_path: str = ""):
        super().__init__(message)
        self.receipt_path = receipt_path


def unavailable_system1(prompt, schema, *, scope, preconditions):
    """Explicit opt-out seam for callers that disable the configured service."""
    return {"available": False, "reason": "System 1 was explicitly disabled by this caller"}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


@lru_cache(maxsize=1)
def hardware_description() -> dict:
    result = {"machine": platform.machine(), "processor": platform.processor(),
              "system": platform.system(), "release": platform.release(),
              "execution": "CPU routing; model hardware provider-owned and unknown",
              "cpuModel": "unavailable", "ramBytes": None}
    if os.name == "nt":
        try:
            process = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                "$cpuInfo=Get-CimInstance Win32_Processor; $computerInfo=Get-CimInstance Win32_ComputerSystem; "
                "@{cpuModel=($cpuInfo.Name -join ', '); ramBytes=$computerInfo.TotalPhysicalMemory} | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=5, check=True, **hidden_windows_subprocess_kwargs())
            result.update(json.loads(process.stdout))
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return result


class Cascade:
    MAX_CACHE = 1000
    MAX_SAMPLES = 10000
    DEFAULT_BUDGETS = {"script": 50, "memory": 25, "system1": 200, "cache": 25,
                       "small": 60000, "big": 120000}

    def __init__(self, root: str | Path, *, budgets_ms: dict | None = None, cache_ttl_seconds: float = 3600):
        self.root = Path(root).resolve()
        self.directory = self.root / ".neyvia" / "efficiency"
        self.cache_path = self.directory / "cache.json"
        self.telemetry_path = self.directory / "latency.json"
        self.transitions = TransitionStore(self.root)
        self.budgets = {**self.DEFAULT_BUDGETS, **(budgets_ms or {})}
        if any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in self.budgets.values()):
            raise ValueError("Latency budgets must be positive milliseconds.")
        if not math.isfinite(cache_ttl_seconds) or cache_ttl_seconds <= 0:
            raise ValueError("Cache expiry must be positive.")
        self.cache_ttl = min(cache_ttl_seconds, 86400)
        self.hardware = hardware_description()

    def metrics(self) -> dict:
        with locked(self.telemetry_path):
            samples = read_json(self.telemetry_path, [])
        groups: dict[str, list[dict]] = {}
        for sample in samples:
            for stage in sample["trace"]:
                key = canonical({"path": sample["path"], "route": sample["route"],
                                 "stage": stage["stage"], "temperature": sample["temperature"],
                                 "hardware": sample["hardware"]})
                groups.setdefault(key, []).append(stage)
            key = canonical({"path": sample["path"], "route": sample["route"], "stage": "request",
                             "temperature": sample["temperature"], "hardware": sample["hardware"]})
            groups.setdefault(key, []).append({"elapsedMs": sample["elapsedMs"], "overBudget": sample["overBudget"]})
        return {"version": 1, "samples": len(samples), "budgetsMs": self.budgets,
                "temperatureDefinition": "cold=first exact request key in workspace; warm=repeated exact key; provider physical weight loading is unknown",
                "timingBoundary": "request samples include learning/cache; stop before telemetry and final receipt writes; constructor excluded",
                "groups": [{**read_key(key), "count": len(items),
                            "p50Ms": _percentile([item["elapsedMs"] for item in items], .5),
                            "p95Ms": _percentile([item["elapsedMs"] for item in items], .95),
                            "overBudgetCount": sum(item["overBudget"] for item in items)}
                           for key, items in groups.items()]}

    def _laya_note(self, scope, prompt, outcome, since, detail="", response=None):
        from .laya_ledger import record
        confidence = (response or {}).get("confidence")
        record(self.root, task=str(scope.get("application") or scope.get("harness") or scope.get("path") or "cascade"), path="cascade.system1", decision="routine-decision",
               outcome=outcome, latency_ms=(time.monotonic() - since) * 1000,
               confidence=confidence if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) else None,
               prompt_chars=len(prompt), detail=detail)

    def decide(self, prompt: str, schema: dict, *, scope: dict, preconditions: dict, validate,
               script=None, system1=None, provider=None, force_big: bool = False,
               timeout: float = 120, learn: bool = True,
               small_model: str = "gpt-6-luna") -> dict:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 256 * 1024:
            raise ValueError("A nonempty prompt of at most 256 KiB is required.")
        if not isinstance(scope, dict) or not isinstance(preconditions, dict) or not callable(validate):
            raise ValueError("Exact scope, preconditions and a semantic answer validator are required.")
        if not math.isfinite(timeout) or timeout <= 0 or timeout > 600:
            raise ValueError("Request timeout must be between 0 and 600 seconds.")
        if small_model not in {"gpt-6-luna", "gpt-6.1-sol"}:
            raise ValueError("Small model must name a supported explicit route.")
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        if scope.get("workspace", str(self.root)) != str(self.root):
            raise ValueError("Scope workspace disagrees with selected root.")
        scope = {**scope, "workspace": str(self.root)}
        # Exact hashes include all values, not embeddings or fuzzy normalizations.
        goal = {"type": "decision", "promptSha256": digest(prompt), "schemaSha256": digest(schema)}
        key = digest({"goal": goal, "scope": scope, "preconditions": preconditions})
        exact_values = bool(re.search(r"\d|\b(?:id|ids|date|dates|ui|value|values)\b", prompt, re.I))
        started = time.monotonic()
        receipt_path = self.directory / "receipts" / (uuid.uuid4().hex + ".json")
        trace: list[dict] = []
        model_calls: list[dict] = []
        answer = None
        route = "failed"
        failure = ""
        escalate = force_big
        winner = None
        winner_route = ""
        with locked(self.cache_path):
            cache = read_json(self.cache_path, {})
        with locked(self.telemetry_path):
            previous = read_json(self.telemetry_path, [])
        temperature = "warm" if any(row.get("key") == key for row in previous) else "cold"

        def stage(name, since, status, *, additional_ms=0, **details):
            elapsed = round((time.monotonic() - since) * 1000 + additional_ms, 3)
            trace.append({"stage": name, "status": status, "elapsedMs": elapsed,
                          "budgetMs": self.budgets[name], "overBudget": elapsed > self.budgets[name], **details})

        def valid(candidate):
            try:
                canonical(candidate)
                if len(canonical(candidate).encode()) > 2 * 1024 * 1024:
                    return False
                validator.validate(candidate)
                if isinstance(candidate, dict) and (candidate.get("escalate") is True or
                        candidate.get("confident") is False or candidate.get("confidence") is False):
                    return False
                confidence = candidate.get("confidence") if isinstance(candidate, dict) else None
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and confidence < .95:
                    return False
                return validate(candidate) is True
            except Exception:
                return False

        def candidate_check(candidate, name):
            nonlocal winner, winner_route, escalate
            if not valid(candidate):
                escalate = True
                return "rejected"
            if winner is not None and canonical(winner) != canonical(candidate):
                escalate = True
                return "disagreement"
            if winner is None:
                winner, winner_route = candidate, name
            return "validated"

        try:
            if not force_big:
                before = time.monotonic()
                if script is None:
                    stage("script", before, "unavailable")
                else:
                    try:
                        value = script()
                        status = "miss" if value is None else candidate_check(value, "script")
                        stage("script", before, status)
                    except Exception as exc:
                        escalate = True
                        stage("script", before, "error", error=type(exc).__name__)
                before = time.monotonic()
                memory = self.transitions.lookup(goal, preconditions, scope)
                if memory["status"] == "conflict":
                    escalate = True
                    stage("memory", before, "conflict", rows=[row["id"] for row in memory["rows"]])
                elif memory["status"] == "match":
                    row = memory["row"]
                    if row["operation"].get("type") != "decision" or row["operation"].get("answer") != row["effect"].get("answer"):
                        escalate = True
                        stage("memory", before, "rejected")
                    else:
                        stage("memory", before, candidate_check(row["effect"]["answer"], "memory"), transitionId=row["id"])
                else:
                    stage("memory", before, "miss")
                # Inspect persisted exact cache as independent available evidence,
                # even when a script/memory candidate exists. Conflicts escalate.
                cache_started = time.monotonic()
                cached = cache.get(key)
                cache_candidate = None
                if cached and cached.get("expiresAt", 0) > time.time():
                    try:
                        self.transitions._receipt(cached, {"answer": cached["answer"]},
                                                  {"type": "decision", "answer": cached["answer"]})
                        source = read_json(Path(cached["receiptPath"]), {})
                        if (cached.get("scope") == scope and cached.get("key") == key and source.get("key") == key
                                and source.get("goal") == goal and source.get("scope") == scope
                                and source.get("preconditions") == preconditions
                                and source.get("cacheExpiresAt") == cached.get("expiresAt")):
                            cache_candidate = cached.get("answer")
                        else:
                            escalate = True
                    except (ValueError, OSError, KeyError, TypeError):
                        # Corrupted or unbound cache evidence is not a trusted hit.
                        escalate = True
                cache_validation_ms = (time.monotonic() - cache_started) * 1000
                if winner is not None and cache_candidate is not None and canonical(winner) != canonical(cache_candidate):
                    escalate = True
                if not escalate and winner is None:
                    before = time.monotonic()
                    # Deterministic values never enter the approximate System 1
                    # route; exact script/memory/cache and checked models remain.
                    if exact_values:
                        stage("system1", before, "bypassed", reason="exact-values")
                        self._laya_note(scope, prompt, "bypassed", before, "exact-values")
                    else:
                        try:
                            if system1 is None:
                                from .laya_service import system1 as laya_system1
                                system1 = laya_system1
                            response = system1(prompt, schema, scope=scope, preconditions=preconditions)
                            if response is None or response.get("available") is False:
                                stage("system1", before, "unavailable", reason=(response or {}).get("reason", "No response"))
                                self._laya_note(scope, prompt, "unavailable", before, (response or {}).get("reason", "No response"))
                            elif response.get("escalate") is True or response.get("confident") is False or not (
                                    response.get("confidence") is True or response.get("confident") is True or
                                    isinstance(response.get("confidence"), (int, float)) and
                                    not isinstance(response.get("confidence"), bool) and response["confidence"] >= .95):
                                escalate = True
                                stage("system1", before, "rejected", reason="confidence-or-escalation", providerDecision=response)
                                self._laya_note(scope, prompt, "escalated", before, "confidence-or-escalation", response)
                            else:
                                status = candidate_check(response.get("answer"), "system1")
                                stage("system1", before, status, providerDecision=response)
                                self._laya_note(scope, prompt, "answered" if status == "validated" else "escalated", before,
                                                "" if status == "validated" else status, response)
                        except Exception as exc:
                            escalate = True
                            stage("system1", before, "error", error=type(exc).__name__)
                            self._laya_note(scope, prompt, "unavailable", before, type(exc).__name__)
                if not escalate:
                    before = time.monotonic()
                    stage("cache", before, "miss" if cache_candidate is None else candidate_check(cache_candidate, "cache"),
                          additional_ms=cache_validation_ms)
                if not escalate and winner is not None:
                    answer, route = winner, winner_route
            if answer is None:
                if provider is None:
                    from .autopilot_model import decide as provider
                stages = [("big", "gpt-6.1-sol")] if escalate else [("small", small_model), ("big", "gpt-6.1-sol")]
                for name, model in stages:
                    before = time.monotonic()
                    remaining = timeout - (before - started)
                    if remaining <= 0:
                        stage(name, before, "budget-exhausted")
                        failure = "Whole request timeout exhausted before provider call."
                        break
                    try:
                        response = provider(prompt, schema, self.root, model=model, timeout=remaining)
                        model_calls.append({"model": model, "receiptPath": response.get("receiptPath", ""),
                                            "tokens": response.get("tokens"), "elapsedMs": response.get("elapsedMs"), "status": "completed"})
                        if valid(response.get("answer")):
                            answer, route = response["answer"], name
                            stage(name, before, "validated")
                            break
                        stage(name, before, "rejected", reason="schema-or-semantic-validation")
                        failure = "Model answer failed schema or semantic validation."
                    except Exception as exc:
                        source_path = getattr(exc, "receipt_path", "")
                        actual = {}
                        if source_path:
                            try:
                                actual = read_json(Path(source_path), {})
                            except (OSError, ValueError):
                                pass
                        model_calls.append({"model": model, "receiptPath": source_path, "tokens": actual.get("tokens"),
                                            "elapsedMs": actual.get("elapsedMs"), "status": "failed", "error": type(exc).__name__})
                        stage(name, before, "error", error=type(exc).__name__)
                        failure = "Requested model route failed: " + type(exc).__name__
                if answer is None and not failure:
                    failure = "No validated answer was available."
            if (time.monotonic() - started) > timeout:
                answer, route = None, "failed"
                failure = "Whole request timeout exceeded; late answer rejected."
        except Exception as exc:
            failure = "Cascade failed: " + type(exc).__name__
            answer, route = None, "failed"

        elapsed = round((time.monotonic() - started) * 1000, 3)
        known_tokens = [call["tokens"] for call in model_calls if isinstance(call.get("tokens"), dict)]
        totals = {field: sum(int(tokens.get(field, 0)) for tokens in known_tokens)
                  for field in ("input", "cachedInput", "output", "total")}
        totals["complete"] = len(known_tokens) == len(model_calls)
        operation = {"type": "decision", "answer": answer}
        receipt = {"version": 1, "status": "completed" if answer is not None else "failed", "answer": answer,
                   "route": route, "key": key, "goal": goal, "scope": scope, "preconditions": preconditions,
                   "operation": operation, "effect": {"answer": answer},
                   "validation": {"schema": answer is not None, "semantic": answer is not None},
                   "tokens": totals, "modelCalls": model_calls, "receiptPath": str(receipt_path),
                   "elapsedMs": elapsed, "trace": trace, "temperature": temperature, "hardware": self.hardware,
                   "temperatureDefinition": "cold=first exact workspace request key; warm=repeated key; provider physical cold/warm unknown",
                   "path": str(scope.get("path", scope.get("harness", "typed-decision"))),
                   "exactValues": exact_values, "budgetMs": timeout * 1000,
                   "cacheExpiresAt": time.time() + self.cache_ttl,
                   "overBudget": elapsed > timeout * 1000, "error": failure if answer is None else ""}
        # The immutable validation receipt is what learning/cache hash-bind.
        # The final request receipt includes persistence/learning time as well.
        source_receipt_path = receipt_path.with_name(receipt_path.stem + ".validated.json")
        atomic_json(source_receipt_path, receipt)
        if answer is not None:
            with locked(self.cache_path):
                cache = read_json(self.cache_path, {})
                cache = {cache_key: row for cache_key, row in cache.items() if row.get("expiresAt", 0) > time.time()}
                cache[key] = {"answer": answer, "expiresAt": receipt["cacheExpiresAt"],
                              "receiptPath": str(source_receipt_path), "sha256": digest(receipt), "scope": scope, "key": key}
                atomic_json(self.cache_path, dict(list(cache.items())[-self.MAX_CACHE:]))
            if learn:
                self.transitions.learn(goal, preconditions, operation, {"answer": answer},
                                       {"type": "escalate", "reason": "validation-or-scope-disagreement"},
                                       {"receiptPath": str(source_receipt_path)}, scope)
        receipt["elapsedMs"] = round((time.monotonic() - started) * 1000, 3)
        receipt["overBudget"] = receipt["elapsedMs"] > timeout * 1000
        receipt["validationReceiptPath"] = str(source_receipt_path)
        if receipt["overBudget"] and answer is not None:
            receipt["persistenceOverBudget"] = True
        with locked(self.telemetry_path):
            samples = read_json(self.telemetry_path, [])
            samples.append({key: receipt[key] for key in ("key", "path", "route", "elapsedMs", "trace",
                                                         "temperature", "hardware", "overBudget", "status")})
            atomic_json(self.telemetry_path, samples[-self.MAX_SAMPLES:])
        receipt["elapsedMs"] = round((time.monotonic() - started) * 1000, 3)
        receipt["overBudget"] = receipt["elapsedMs"] > timeout * 1000
        receipt["timingBoundary"] = "includes model transport, cache, learning and telemetry; excludes constructor and final receipt write"
        atomic_json(receipt_path, receipt)
        if answer is None:
            raise CascadeError(failure, str(receipt_path))
        return receipt


def read_key(value: str) -> dict:
    import json
    return json.loads(value)
