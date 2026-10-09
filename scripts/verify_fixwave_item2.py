"""Profile-to-mission acceptance call, bounded to one Claude plan-limits turn.

Uses the actual stores, approval, dispatch and broker; never replaces an adapter,
answers folder trust, changes global settings or falls back to a paid API.
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from grant_agent.neyvia_missions import call
from grant_agent.neyvia_runtime import mission_route, request
from grant_agent.neyvia_workspace_tools import workspace_for
from grant_agent.nightshift import nightshift_for
from grant_agent.web_backend import FluxioWebBackend


def main():
    root = REPO / ".agent_control" / ("fixwave-item2-" + uuid.uuid4().hex)
    (root / "config").mkdir(parents=True)
    (root / "config" / "capability_packs.json").write_text("{}", encoding="utf-8")
    os.environ["NEYVIA_UI_STATE_ROOT"] = str(root)
    backend = FluxioWebBackend(root, REPO / "web")
    workspace = workspace_for(root, backend)
    service = nightshift_for(root, backend)
    broker = workspace.broker()
    receipt = {"item": 2, "scratchRoot": str(root), "checks": [], "missing": []}

    def check(name, condition):
        assert condition, name
        receipt["checks"].append(name)

    def store(name, route):
        return request(workspace, {"action": "profile", "name": name, "route": route}, "POST")

    def start(identity):
        args = {"id": identity, "action": "start"}
        pending = call(service, "mission.control", args)
        check(identity + " requests exact mission approval", pending.get("status") == "approval_required")
        workspace.approve(pending["approvalId"])
        return call(service, "mission.control", args)

    try:
        options = broker.provider_options("claude-code")
        models = options.get("models", [])
        model = next((row["id"] for row in models if row["id"] == "haiku"),
                     next((row["id"] for row in models if row["id"] == "sonnet"), models[0]["id"]))
        route = {"app": "claude-code", "model": model, "permissionMode": "plan", "transport": "terminal"}
        store("planner", route)
        store("executor", route)
        check("profile store roundtrips terminal route", workspace.bus.get("runtime.profiles")["planner"] == route)
        check("unrouted task uses configured executor", mission_route(root, {"prompt": "x"})["routingProfile"] == "executor")
        check("explicit task keeps its own route", mission_route(root, {"harness": "codex", "model": "explicit"})["model"] == "explicit")
        for task in ({"routingProfile": "planner", "model": "override"}, {"routingProfile": "classifier"}):
            try:
                mission_route(root, task)
            except ValueError:
                receipt["checks"].append("reject conflicting/unconfigured profile: " + str(task))
            else:
                raise AssertionError("Silently accepted invalid profile")

        created = call(service, "mission.create", {
            "id": "profile-proof", "goal": "Verify profile dispatch", "folder": str(root),
            "acceptanceChecks": ["Claude reports the exact fixture marker"],
            "budget": {"maxTaskSeconds": 55}, "tasks": [{"id": "marker", "routingProfile": "planner",
                "prompt": "Reply exactly FIXWAVE_PROFILE_EXECUTED. Do not call tools, inspect or modify files, or start subagents."}]})
        saved = service.get("profile-proof:marker")
        check("creation freezes profile harness/model/transport", saved["harness"] == "claude-code" and saved["model"] == model and saved["transport"] == "terminal")
        store("planner", None)
        check("profile deletion cannot reroute approved task", service.get(saved["id"])["model"] == model)
        start("profile-proof")
        deadline = time.monotonic() + 65
        latest_run = None
        while time.monotonic() < deadline:
            task = service.get(saved["id"])
            if task.get("runId"):
                try:
                    latest_run = broker.get_run(task["runId"])
                except Exception as exc:
                    if getattr(exc, "code", None) != "run_not_found":
                        raise
                if latest_run and latest_run.get("pendingRequest"):
                    pending = latest_run["pendingRequest"]
                    receipt["inputBoundary"] = {key: pending.get(key) for key in ("type", "tool", "toolName", "title")}
                    receipt["missing"].append("Actual Claude terminal needs explicit user input/trust; no global trust was changed")
                    service.stop(task["id"], "Verification stopped at explicit input boundary")
                    break
            if task["status"] in {"done", "blocked"}:
                break
            time.sleep(0.25)
        else:
            service.stop(saved["id"], "Verification deadline reached")
            receipt["missing"].append("Plan-limits turn did not complete within 65 seconds")
        # stop() signals the process; wait for its actual terminal event before
        # recording completion or releasing the folder lock.
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            task = service.get(saved["id"])
            if task["status"] in {"done", "blocked"}:
                break
            if task.get("runId"):
                latest_run = broker.get_run(task["runId"])
                service.finish_run(latest_run)
            time.sleep(0.1)
        task = service.get(saved["id"])
        if latest_run:
            latest_run = broker.get_run(task["runId"])
        receipt["mission"] = {key: task.get(key) for key in ("id", "routingProfile", "harness", "model", "permissionMode", "transport", "status", "reason", "runId", "evidence")}
        if latest_run:
            receipt["brokerRun"] = {key: latest_run.get(key) for key in ("app", "model", "permissionMode", "state", "error", "sessionId")}
            check("real broker records selected app/model", latest_run["app"] == route["app"] and latest_run["model"] == model)
        if task["status"] != "done":
            receipt["missing"].append("Provider completion unproven: " + str(task.get("reason")))
        else:
            page = broker.read(latest_run["sessionId"])
            check("completed real turn includes fixture marker", any("FIXWAVE_PROFILE_EXECUTED" in str(item.get("data", {}).get("text", "")) and item.get("kind") == "assistant" for item in page.get("items", [])))
            receipt["checks"].append("Real Claude plan-limits mission completed")

        call(service, "mission.control", {"id": "profile-proof", "action": "redirect", "taskId": saved["id"], "model": "explicit-route"})
        check("explicit redirect detaches saved profile provenance", "routingProfile" not in service.get(saved["id"]))

        # A current owner ceiling must apply even after a profile was snapshotted.
        store("verifier", {**route, "permissionMode": "acceptEdits"})
        call(service, "mission.create", {"id": "policy-proof", "goal": "Check tightened owner ceiling", "folder": str(root),
            "acceptanceChecks": ["No model call under a tightened permission ceiling"],
            "tasks": [{"id": "blocked", "routingProfile": "verifier", "prompt": "Never execute under this owner ceiling"}]})
        request(workspace, {"action": "policy", "app": "claude-code", "permissionCeiling": "read-only", "allowedModels": [model]}, "POST")
        start("policy-proof")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and service.get("policy-proof:blocked")["status"] != "blocked":
            time.sleep(0.05)
        blocked = service.get("policy-proof:blocked")
        check("actual dispatch rechecks current permission ceiling", blocked["status"] == "blocked" and "runtime ceiling" in blocked["reason"])
        receipt["policyRefusal"] = {key: blocked.get(key) for key in ("harness", "model", "status", "reason")}
        receipt["missing"].append("Learned router, automatic task decomposition and outcome-based Evolver tuning remain outside item 2")
    finally:
        for task in service.tasks():
            if task["status"] == "running":
                service.stop(task["id"], "Acceptance cleanup")
        service.close()
        workspace.close()
        broker.close()
        target = REPO / "scripts" / "evidence" / "fixwave-item2.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checks": len(receipt["checks"]), "mission": receipt.get("mission"), "missing": receipt["missing"]}, indent=2))


if __name__ == "__main__":
    main()
