"""Production Connected Language and grounded flow receipts for owned C1 apps."""
from __future__ import annotations

import time

from grant_agent.neyvia_cua import CuaService


def flow_selector(node, *, mutable_label=False):
    """Keep editable text out of identity; the production resolver checks uniqueness."""
    selector = {"role": node["role"], "className": node.get("className", "")}
    if node.get("automationId"):
        selector["automationId"] = node["automationId"]
    elif not mutable_label:
        selector["label"] = node.get("name", "")
    return selector


def frozen_steps(task, attempts):
    """Translate only a complete verified cohort, preserving its postconditions."""
    if len(attempts) != task.get("repetitions", 5) or not all(a.get("passed") for a in attempts):
        raise ValueError("Learning requires every frozen action to have passed")
    labels = {}
    mutable_labels = set()
    if task["action"] == "value":
        for attempt in attempts:
            node = attempt["nativeNode"]
            labels.setdefault(node["id"], set()).add(node.get("name", ""))
            if node.get("name") and (node["name"] == node.get("value") or node["name"] in task["values"]):
                mutable_labels.add(node["id"])
        mutable_labels.update(key for key, names in labels.items() if len(names) > 1)
    steps = []
    for attempt in attempts:
        action = task["action"]
        node = attempt["nativeNode"]
        target = flow_selector(node, mutable_label=node["id"] in mutable_labels)
        if action == "value":
            value = attempt["request"]["text"]
            tool, args = "set_value", {"value": value}
            check = {"selector": target, "value_equals": value}
        elif action == "select":
            tool, args = "click", {}
            check = {"selector": target, "selected_equals": True}
        elif action == "calculator":
            native_check = attempt["request"]["expect"][0]
            # Native name_contains is the same grounded label predicate here;
            # include the result identity so any unrelated digit cannot pass.
            result = native_check["selector"]
            if set(result) != {"automationId"} or "name_contains" not in native_check:
                raise ValueError("Calculator flow requires the frozen result identity and digit check")
            tool, args = "click", {}
            check = {"selector": {**result, "label_contains": native_check["name_contains"]}, "exists": True}
        else:
            raise ValueError("No exact frozen flow action mapping for this task")
        steps.append({"selector": target, "tool": tool, "args": args, "expect": [{"element": check}]})
    return steps


class CohortLearning:
    def __init__(self, worker, scratch, window):
        self.service = CuaService(scratch)
        self.service.native.close()
        self.service.native = worker
        self.window = window
        self.session = self.service.new_session(
            [window["processName"]], {"chatId": "c11-cohort", "app": "neyvia"})
        self.session["_windowPins"] = {int(window["windowId"]): window}
        self.params = {"sessionId": self.session["id"], "window_id": int(window["windowId"])}
        self.states = []

    def observe(self):
        started = time.perf_counter()
        state = self.service.request("inspect", {**self.params, "diff_only": True})
        self.states.append(state)
        return {"state": state, "elapsedMs": round((time.perf_counter() - started) * 1000, 2)}

    def adapt(self):
        return self.service.request("adapt", self.params)

    def compile_task(self, task, attempts):
        """Replay the frozen distinct values, retaining actual native verifiers."""
        if task["action"] not in {"value", "select", "calculator"}:
            return {"status": "unsupported", "reason": "No exact frozen flow action mapping for this task"}
        steps = frozen_steps(task, attempts)
        runs = []
        for _ in range(5):
            outcome = self.service.request("flow", {**self.params, "steps": steps})
            runs.append(outcome)
            if not outcome.get("ok"):
                break
        final_check = self.service.request("verify", {
            **self.params, "expect": steps[-1]["expect"]})
        passed = (len(runs) == 5 and all(r.get("ok") for r in runs)
                  and runs[-1].get("compiled") and final_check.get("status") == "satisfied")
        return {"status": "passed" if passed else "failed", "runs": runs,
                "compiledReplay": bool(runs and runs[-1].get("compiled")),
                "tokens": sum(r.get("tokens", 0) for r in runs), "finalObservedState": final_check,
                "steps": steps,
                "timingBoundary": "Additional production learning replays, separate from frozen five-action latency"}

    def close(self):
        self.session.update(status="ended", control="paul")
        self.service.shutdown()
