"""Admission and event-driven limits; cancellation retains the repository lock."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta, timezone

from . import nightshift_ledger as ledger

DEFAULTS = {"paused": False, "maxConcurrent": 4, "perHarness": {},
            "maxTaskSeconds": None, "maxTaskTokens": None, "gpuReservedFor": "ASR",
            "holdAtPlanPercent": 70, "perHarnessBudgets": {}, "maxNightSeconds": None,
            "quietGpuHours": None}
PLAN_APPS = {"claude-code": "Claude Code", "codex": "Codex", "opencode": "OpenCode"}


def positive(value, field):
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
        raise ValueError(field + " must be a positive integer or null")
    return value


def validate_policy(current, patch):
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError("Unknown resource control")
    value = {**current, **patch}
    if not isinstance(value["paused"], bool) or not isinstance(value["perHarness"], dict):
        raise ValueError("paused must be boolean; perHarness must be an object")
    for key in ("maxConcurrent", "maxTaskSeconds", "maxTaskTokens", "maxNightSeconds"):
        positive(value[key], key)
    for app, limit in value["perHarness"].items():
        if app not in ledger.HARNESSES:
            raise ValueError("Unknown harness")
        positive(limit, app)
    budgets = value["perHarnessBudgets"]
    if not isinstance(budgets, dict):
        raise ValueError("perHarnessBudgets must be an object")
    for app, budget in budgets.items():
        if app not in ledger.HARNESSES or not isinstance(budget, dict) or set(budget) - {"maxTokens", "maxSeconds"}:
            raise ValueError("Unknown harness budget")
        for key, limit in budget.items():
            positive(limit, key)
    quiet = value["quietGpuHours"]
    if quiet is not None:
        if not isinstance(quiet, dict) or set(quiet) != {"start", "end", "timeZone"}:
            raise ValueError("quietGpuHours requires start, end and timeZone")
        if quiet["timeZone"] not in {"local", "UTC"} or any(not isinstance(quiet[key], str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", quiet[key]) for key in ("start", "end")):
            raise ValueError("quietGpuHours requires HH:MM times and local or UTC timeZone")
    if value["gpuReservedFor"] is not None and not isinstance(value["gpuReservedFor"], str):
        raise ValueError("gpuReservedFor must be a name or null")
    hold = value["holdAtPlanPercent"]
    if hold is not None and (not isinstance(hold, int) or isinstance(hold, bool) or not 1 <= hold <= 100):
        raise ValueError("holdAtPlanPercent must be 1-100 or null")
    return value


def quiet_window(policy, current=None):
    """Return active flag and next civil-time boundary; equal endpoints mean all day."""
    quiet = policy.get("quietGpuHours")
    if not quiet:
        return False, None
    current = current or datetime.now(timezone.utc)
    current = current.astimezone(timezone.utc) if quiet["timeZone"] == "UTC" else current.astimezone()
    start, end = (int(value[:2]) * 60 + int(value[3:]) for value in (quiet["start"], quiet["end"]))
    minute = current.hour * 60 + current.minute
    active = start == end or (start <= minute < end if start < end else minute >= start or minute < end)
    if start == end:
        return True, None
    boundaries = []
    for offset in (0, 1, 2):
        date = current.date() + timedelta(days=offset)
        for value in (start, end):
            naive = datetime.combine(date, datetime.min.time()).replace(hour=value // 60, minute=value % 60)
            boundary = naive.replace(tzinfo=timezone.utc) if quiet["timeZone"] == "UTC" else naive.astimezone()
            if boundary > current:
                boundaries.append(boundary)
    return active, min(boundaries) if boundaries else None


class Resources:
    def __init__(self, service):
        self.service = service
        self.timers = {}
        ledger.initialize(service)

    def policy(self):
        return {**DEFAULTS, **self.service.bus.get("nightshift.resources", {})}

    def update(self, patch):
        value = validate_policy(self.policy(), patch)
        with self.service.lock:
            from .neyvia_settings import update
            from .neyvia_workspace_tools import workspace_for
            update(workspace_for(self.service.bus.root, self.service.backend), {"nightShift": value})
            self.refresh_timers()
            for task in self.service.tasks():
                if task["status"] == "running" and task.get("runId"):
                    self.watch(task)
            self.service.dispatch()
        return value

    def wait_reason(self, task, running):
        policy = self.policy()
        self.refresh_timers()
        if policy["paused"]:
            return "Night Shift is paused"
        totals = ledger.summary(self.service)
        if policy["maxNightSeconds"] and totals["night"]["elapsedSeconds"] >= policy["maxNightSeconds"]:
            return "Night wall time budget exhausted; start a new night explicitly"
        budget = policy["perHarnessBudgets"].get(task["harness"]) or {}
        usage = totals["perHarness"][task["harness"]]
        token_cap = budget.get("maxTokens") or policy["maxTaskTokens"] or task.get("limits", {}).get("maxTaskTokens")
        if token_cap and task["harness"] == "opencode":
            return "Token limit requires a harness that reports live usage"
        if budget.get("maxTokens") and usage["unknownCompletedRuns"]:
            return "Harness token budget held: completed attempt token usage is unknown"
        for maximum, observed, label in (("maxTokens", "reportedTokens", "token"), ("maxSeconds", "elapsedSeconds", "wall time")):
            if budget.get(maximum) and usage[observed] >= budget[maximum]:
                return f"Harness {label} budget exhausted"
        if any(budget.get(key) for key in ("maxTokens", "maxSeconds")) and any(row["harness"] == task["harness"] for row in running):
            return "Harness budget serializes attempts"
        limit = policy["maxConcurrent"]
        if limit and len(running) >= limit:
            return "Concurrent task limit"
        limit = policy["perHarness"].get(task["harness"])
        if limit and sum(row["harness"] == task["harness"] for row in running) >= limit:
            return "Harness concurrency limit"
        if task.get("requiresGpu"):
            if policy["gpuReservedFor"]:
                return "GPU reserved for " + policy["gpuReservedFor"]
            if quiet_window(policy)[0]:
                return "GPU quiet hours"
            if any(row.get("requiresGpu") for row in running):
                return "Another Night Shift task holds the GPU"
        hold = policy["holdAtPlanPercent"]
        if task.get("missionId"):
            from .neyvia_missions import records
            mission = next((row for row in records(self.service) if row["id"] == task["missionId"]), {})
            hold = mission.get("holdAtPlanPercent", hold)
        return self.plan_hold(task, hold)

    def remaining_limits(self, task):
        """Return attempt limits without changing the user's stored task definition."""
        policy = self.policy()
        totals = ledger.summary(self.service)
        budget = policy["perHarnessBudgets"].get(task["harness"]) or {}
        usage = totals["perHarness"][task["harness"]]
        limits = {}
        for key, cap, used in (("maxTaskTokens", "maxTokens", "reportedTokens"), ("maxTaskSeconds", "maxSeconds", "elapsedSeconds")):
            values = [value for value in (policy[key], task.get("limits", {}).get(key)) if value is not None]
            if budget.get(cap):
                values.append(max(0.0, budget[cap] - usage[used]))
            if key == "maxTaskSeconds" and policy["maxNightSeconds"]:
                values.append(max(0.0, policy["maxNightSeconds"] - totals["night"]["elapsedSeconds"]))
            limits[key] = min(values) if values else None
        return limits

    def plan_hold(self, task, hold):
        app = task.get("harness")
        if not hold or app not in PLAN_APPS:
            return None
        from .connected_sessions.live_limits import service_for
        try:
            root = getattr(getattr(self.service, "broker", None), "root", None)
            if root is None:
                return "Holding: plan limits are unavailable"
            state = service_for(root).snapshot()
            rows = [row for row in state["limits"] if row.get("app") == app]
        except Exception:
            return "Holding: plan limits are unavailable"
        if not rows or any(row.get("stale") for row in rows):
            return f"Holding: {PLAN_APPS[app]} plan limits are unavailable or stale; refresh required"
        if app == "claude-code" and not {"five_hour", "seven_day"} <= {row.get("window") for row in rows}:
            return "Holding: Claude Code has not reported both plan windows"
        current = datetime.now(timezone.utc)
        for row in rows:
            used, resets = row.get("usedPercent"), row.get("resetsAt")
            if row.get("status") == "rejected":
                return f"Holding: {PLAN_APPS[app]} CLI reports the account limit is reached"
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not resets:
                return f"Holding: {PLAN_APPS[app]} plan limits are incomplete"
            if used < hold:
                continue
            try:
                when = ledger.timestamp(resets)
            except ValueError:
                continue
            if when <= current:
                continue
            self.wake_at(when, "plan-reset:" + app)
            local = when.astimezone().strftime("%H:%M")
            return f"Holding: {PLAN_APPS[app]} {row.get('label') or row.get('window')} limit at {round(used)}% (resets {local})"
        return None

    def wake_at(self, when, key="plan-reset", callback=None):
        delay = max(0.05, (when - datetime.now(timezone.utc)).total_seconds() + 0.05)
        timer = self.timers.get(key)
        if timer and timer.is_alive() and getattr(timer, "due", None) == when:
            return
        self.release(key)
        def wake():
            with self.service.lock:
                if self.service.closed.is_set():
                    return
                if self.timers.get(key) is timer:
                    self.timers.pop(key, None)
                (callback or self.service.dispatch)()
        timer = threading.Timer(delay, wake)
        timer.daemon, timer.due = True, when
        self.timers[key] = timer
        timer.start()

    def refresh_timers(self):
        policy = self.policy()
        _, boundary = quiet_window(policy)
        if boundary:
            self.wake_at(boundary, "quiet-boundary", self.policy_boundary)
        else:
            self.release("quiet-boundary")
        if policy["maxNightSeconds"]:
            deadline = ledger.timestamp(ledger.period(self.service)["startedAt"]) + timedelta(seconds=policy["maxNightSeconds"])
            if deadline > datetime.now(timezone.utc):
                self.wake_at(deadline, "night-deadline", self.policy_boundary)
            else:
                self.release("night-deadline")
        else:
            self.release("night-deadline")

    def policy_boundary(self):
        self.refresh_timers()
        for task in self.service.tasks():
            if task["status"] == "running" and task.get("runId"):
                self.watch(task)
        self.service.dispatch()

    def release(self, identity):
        timer = self.timers.pop(identity, None)
        if timer:
            timer.cancel()

    def watch(self, task):
        if not task:
            return
        with self.service.lock:
            self.release(task["id"])
            try:
                run = self.service.broker.get_run(task["runId"])
            except Exception as exc:
                if getattr(exc, "code", None) == "run_not_found":
                    return
                raise
            if task["status"] != "running" or run["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                return
            policy = self.policy()
            plan_reason = self.plan_hold(task, policy["holdAtPlanPercent"])
            if plan_reason:
                self.service.stop(task["id"], "Resource limit: " + plan_reason)
                return
            totals = ledger.summary(self.service)
            if policy["maxNightSeconds"] and totals["night"]["elapsedSeconds"] >= policy["maxNightSeconds"]:
                self.service.stop(task["id"], "Resource limit: night wall time reached")
                return
            if task.get("requiresGpu") and (policy["gpuReservedFor"] or quiet_window(policy)[0]):
                reason = "GPU reserved for " + policy["gpuReservedFor"] if policy["gpuReservedFor"] else "GPU quiet hours"
                self.service.stop(task["id"], "Resource limit: " + reason)
                return
            row = ledger.attempt(self.service, task["runId"])
            saved = json.loads(row["effective_limits"]) if row and row["effective_limits"] else {}
            limits = {}
            for key in ("maxTaskTokens", "maxTaskSeconds"):
                values = [value for value in (policy[key], task.get("limits", {}).get(key), saved.get(key)) if value is not None]
                limits[key] = min(values) if values else None
            tokens = (run.get("usage") or {}).get("totalTokens")
            reported = bool((run.get("usage") or {}).get("reportedByTransport"))
            budget = policy["perHarnessBudgets"].get(task["harness"]) or {}
            usage = totals["perHarness"][task["harness"]]
            if budget.get("maxTokens") and usage["reportedTokens"] >= budget["maxTokens"]:
                self.service.stop(task["id"], "Resource limit: harness token budget reached")
                return
            if limits["maxTaskTokens"] is not None and run.get("usage") and (tokens is None or not reported):
                self.service.stop(task["id"], "Resource limit: task token usage is unavailable")
                return
            if limits["maxTaskTokens"] is not None and isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= limits["maxTaskTokens"]:
                self.service.stop(task["id"], "Resource limit: reported task tokens reached " + str(tokens))
                return
            started = ledger.timestamp(row["started"]) if row and row["started"] else (ledger.timestamp(run["startedAt"]) if run.get("startedAt") else datetime.now(timezone.utc))
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            deadlines = []
            if limits["maxTaskSeconds"] is not None:
                deadlines.append(limits["maxTaskSeconds"] - elapsed)
            if budget.get("maxSeconds"):
                deadlines.append(budget["maxSeconds"] - usage["elapsedSeconds"])
            if policy["maxNightSeconds"]:
                deadlines.append(policy["maxNightSeconds"] - totals["night"]["elapsedSeconds"])
            if deadlines:
                remaining = min(deadlines)
                if remaining <= 0:
                    self.expire(task["id"], task["runId"])
                else:
                    self.wake_at(datetime.now(timezone.utc) + timedelta(seconds=remaining), task["id"], lambda: self.expire(task["id"], task["runId"]))
            self.refresh_timers()

    def expire(self, identity, run_id):
        with self.service.lock:
            if self.service.closed.is_set():
                return
            task = self.service.get(identity)
            if task and task["status"] == "running" and task["runId"] == run_id:
                self.service.stop(identity, "Resource limit: task or harness wall time reached")
