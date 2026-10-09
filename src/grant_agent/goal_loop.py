"""Explicit native goal checkpoints; a model reply is not a completion signal.

Session ownership is held by run_owned. Checkpoints survive compaction/restarts,
but a new user turn must explicitly activate its goal again (no stale auto-run).
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .durability import atomic_write_json

RUNTIME_GOAL_PREFIX = "[Neyvia runtime goal checkpoint — not a new user request]"

GOAL_TOOL_DESCRIPTION = (
    "Track a multi-step task through execution and verification. At the start of substantial "
    "work call action=start with the user's goal, acceptance checks and next_action. "
    "Use progress to save evidence and the next concrete action before ending an unfinished "
    "round. An active goal continues automatically after a reply; perform the next action "
    "rather than asking whether to do already requested work. Use complete only with "
    "acceptance evidence, or blocked with the specific blocker. Use neyvia_ask_user for a "
    "necessary question; never infer an answer. Use pause only when the user explicitly asks "
    "you to pause or stop this goal; preserve the checkpoint and end the current run without "
    "treating it as blocked. A later explicit user instruction can start the resumed work. inspect "
    "retrieves the previous checkpoint "
    "after compaction or interruption. A new user turn must explicitly start its current goal; "
    "do not resume unrelated work. This does not change permissions or the user's scope. "
    "Simple questions/greetings need no goal. There is no automatic time or round cutoff "
    "for an active goal. If an approach fails, diagnose why and try a materially different "
    "in-scope approach using the evidence. Repeated tool results do not count as progress. "
    "Before reporting a blocker, investigate available alternatives; describe what was tried "
    "and the missing dependency. Never claim completion just because an attempt ended."
)


def _stable_observation(value):
    if isinstance(value, str):
        try:
            return _stable_observation(json.loads(value))
        except (ValueError, TypeError):
            return value
    if isinstance(value, dict):
        volatile = {"timestamp", "at", "createdat", "updatedat", "startedat", "finishedat",
                    "elapsedms", "durationms", "elapsedseconds", "durationseconds", "callid", "runid", "actionid",
                    "receiptid", "operationid", "eventid", "invocationid", "requestid", "receiptpath"}
        return {key: _stable_observation(item) for key, item in value.items()
                if str(key).lower().replace("_", "") not in volatile}
    if isinstance(value, list):
        return [_stable_observation(item) for item in value]
    return value


class GoalLoop:
    def __init__(self, root: Path, session_id: str):
        key = hashlib.sha256(session_id.encode()).hexdigest()
        self.path = Path(root) / ".agent_control" / "neyvia_agent" / "goals" / f"{key}.json"
        self.state = None
        self.started = time.monotonic()
        self.rounds = 0
        self.requests = 0
        self.stop_reason = "not_started"
        self.observations: set[str] = set()
        self.last_observations = 0
        self.stagnant_rounds = 0
        self.last_attempt = ""
        self.repeated_attempts = 0

    def activate(self, request: str) -> None:
        """Explicit UI goal mode arms this turn even if its first reply is a plan."""
        previous = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        previous_goal = previous.get("checkpoint") or {}
        self.state = {"schema": "neyvia.goal.v1", "source": "current_user_request",
                      "goal": request if len(request) <= 8000 else request[:7800] + "\n[Full request retained in session history]",
                      "requestHash": hashlib.sha256(request.encode()).hexdigest(),
                      "acceptance": "Fulfil the current user request and verify its requested outcome.",
                      "status": "active", "evidence": "", "nextAction": "Execute and verify the current user request.",
                      "blocker": ""}
        if previous_goal.get("status") in {"active", "paused", "blocked"}:
            self.state["previousUnfinishedGoal"] = {
                key: previous_goal[key] for key in ("goal", "acceptance", "evidence", "nextAction", "blocker")
                if key in previous_goal
            }
        self.save()

    def update(self, action: str, goal: str = "", acceptance: str = "", evidence: str = "",
               next_action: str = "", blocker: str = "") -> dict:
        if action == "inspect":
            previous = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None
            return {"checkpoint": self.state or (previous or {}).get("checkpoint"),
                    "activeThisTurn": self.state is not None}
        if action not in {"start", "progress", "complete", "blocked", "pause"}:
            raise ValueError("Use start, progress, complete, blocked, pause or inspect")
        for value in (goal, acceptance, evidence, next_action, blocker):
            if not isinstance(value, str) or len(value) > 8000:
                raise ValueError("Goal fields must be strings of at most 8000 characters")
        if action == "start":
            if self.state is not None and self.state.get("source") != "current_user_request":
                raise ValueError("This turn already has a goal; use progress instead of resetting it")
            if not all(value.strip() for value in (goal, acceptance, next_action)):
                raise ValueError("Starting a goal requires goal, acceptance and next_action")
            self.state = {**(self.state or {}), "schema": "neyvia.goal.v1", "source": "model_checkpoint",
                          "goal": goal, "acceptance": acceptance}
        elif self.state is None:
            raise ValueError("Start the current user goal before updating it")
        if action == "progress" and not (evidence.strip() and next_action.strip()):
            raise ValueError("Progress needs evidence and a next_action")
        if action == "complete" and not evidence.strip():
            raise ValueError("Completion needs acceptance evidence")
        if action == "blocked" and not blocker.strip():
            raise ValueError("Describe the concrete blocker")
        if action == "pause" and self.state.get("status") != "active":
            raise ValueError("Only an active goal can be paused")
        if action == "pause":
            evidence = evidence or self.state.get("evidence", "")
            next_action = next_action or self.state.get("nextAction", "")
            blocker = blocker or self.state.get("blocker", "")
        self.state.update(status={"start": "active", "progress": "active", "complete": "completed",
                                 "blocked": "blocked", "pause": "paused"}[action],
                          evidence=evidence, nextAction=next_action, blocker=blocker)
        self.stop_reason = ""
        self.save()
        return self.receipt()

    def observe(self, items) -> None:
        for item in items:
            if getattr(item, "type", "") != "tool_call_output_item":
                continue
            name = getattr(item, "tool_name", "")
            raw = getattr(item, "raw_item", {})
            output = getattr(item, "output", None)
            # Goal bookkeeping, timestamps and call ids alone cannot keep a run alive.
            if name == "neyvia_goal" or (isinstance(output, str) and '"neyvia.goal.v1"' in output):
                continue
            if output is None and isinstance(raw, dict):
                output = raw.get("output")
            if output is not None:
                self.observations.add(hashlib.sha256(json.dumps(_stable_observation(output), sort_keys=True, default=str).encode()).hexdigest())

    def after_round(self, *, requests: int, pending_question: bool, batch_limit: bool = False,
                    final_output: str = "") -> str | None:
        self.rounds += 1
        self.requests += requests
        if not self.state:
            return None
        fresh = len(self.observations) > self.last_observations
        self.last_observations = len(self.observations)
        self.stagnant_rounds = 0 if fresh else self.stagnant_rounds + 1
        attempt = hashlib.sha256(json.dumps([self.state, final_output], sort_keys=True).encode()).hexdigest()
        self.repeated_attempts = self.repeated_attempts + 1 if not fresh and attempt == self.last_attempt else 1
        self.last_attempt = attempt
        if pending_question:
            self.stop_reason = "input_required"
        elif self.state["status"] != "active" and not (batch_limit and self.state["status"] == "completed"):
            self.stop_reason = self.state["status"]
        elif self.stagnant_rounds >= 4 and self.repeated_attempts >= 3:
            # This guard never watches wall time or an in-flight tool. It only
            # fires after multiple completed rounds ignore two recovery prompts
            # with the exact same checkpoint/reply and no new tool observation.
            self.stop_reason = "repeated_unchanged_work"
            self.state["blocker"] = (
                "Repeated the same checkpoint and reply without new tool evidence after "
                "two requests to diagnose the failure and change approach. The goal is unfinished."
            )
        else:
            self.stop_reason = ""
        self.save()
        if self.stop_reason:
            return None
        return (
            RUNTIME_GOAL_PREFIX + "\n"
            "Continue the current user goal. If its completion has been verified, report the result. "
            "Otherwise perform the next authorized concrete action "
            "and verify its result in this run. Do not just propose future work. If finished, "
            "record complete with evidence; if genuinely blocked, record the blocker or ask the "
            "necessary question. Follow the original user scope and instructions.\n"
            + ("The recent rounds yielded no new tool evidence. Diagnose the failed approach and "
               "try a materially different method or gather the missing evidence. Do not repeat "
               "the same plan or tool calls.\n" if self.stagnant_rounds >= 2 else "")
            + json.dumps(self.state, ensure_ascii=False)
        )

    def receipt(self) -> dict:
        return {"checkpoint": self.state, "rounds": self.rounds, "requests": self.requests,
                "stopReason": self.stop_reason, "elapsedSeconds": round(time.monotonic() - self.started, 3),
                "distinctToolResults": len(self.observations), "stagnantRounds": self.stagnant_rounds,
                "repeatedIdenticalAttempts": self.repeated_attempts}

    def save(self):
        if self.state:
            atomic_write_json(self.path, self.receipt())
