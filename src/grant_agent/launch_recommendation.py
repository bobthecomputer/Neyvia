from __future__ import annotations

from .proofs_c_models import checked

import re
from typing import Any

CANONICAL_PLANNER_PROVIDER = "openai-codex"
CANONICAL_PLANNER_MODEL = "gpt-5.6-sol"
CANONICAL_EXECUTOR_PROVIDER = "opencode-go"
CANONICAL_EXECUTOR_MODEL = "opencode-go/deepseek-v4-pro"
CANONICAL_VERIFIER_PROVIDER = "openai-codex"
CANONICAL_VERIFIER_MODEL = "gpt-5.6-sol"

CONTEXT_READER_LANE: dict[str, str] = {
    "role": "context-reader",
    "provider": "neyvia-context",
    "model": "receipt-bound-cache",
    "effort": "retrieval",
    "reason": (
        "Neyvia reads cached and workspace context first, records the selected sources, "
        "and hands the smallest relevant evidence bundle to the planner and executor."
    ),
}

TASK_RECOMMENDATIONS: list[dict[str, Any]] = [
    {
        "taskType": "frontend_design",
        "taskLabel": "Frontend/UI/design",
        "keywords": (
            "frontend",
            "front-end",
            "ui",
            "ux",
            "interface",
            "design",
            "react",
            "css",
            "website",
            "mobile",
            "tablet",
        ),
        "provider": CANONICAL_EXECUTOR_PROVIDER,
        "model": CANONICAL_EXECUTOR_MODEL,
        "effort": "high",
        "reason": "DeepSeek V4 Pro executes UI work through the genuine OpenCode Go route while Neyvia keeps the mission durable and receipt-bound.",
    },
    {
        "taskType": "hardware_electrical",
        "taskLabel": "Hardware/electrical engineering",
        "keywords": (
            "hardware",
            "electrical",
            "electronics",
            "pcb",
            "circuit",
            "sensor",
            "embedded",
            "microcontroller",
            "firmware",
            "simulation",
        ),
        "provider": CANONICAL_EXECUTOR_PROVIDER,
        "model": CANONICAL_EXECUTOR_MODEL,
        "effort": "high",
        "reason": "DeepSeek V4 Pro executes the engineering work through OpenCode Go; GPT-5.6 Sol verifies constraints, units, and artifacts independently.",
    },
    {
        "taskType": "data_f1_analytics",
        "taskLabel": "F1/data analytics",
        "keywords": (
            "f1",
            "formula 1",
            "formula one",
            "telemetry",
            "lap time",
            "racing",
            "analytics",
            "dashboard",
            "visualization",
        ),
        "provider": CANONICAL_EXECUTOR_PROVIDER,
        "model": CANONICAL_EXECUTOR_MODEL,
        "effort": "high",
        "reason": "DeepSeek V4 Pro executes the analytics work through OpenCode Go while GPT-5.6 Sol checks the evidence and calculations.",
    },
    {
        "taskType": "security_red_team",
        "taskLabel": "Security/red-team",
        "keywords": (
            "red team",
            "red-team",
            "defensive",
            "threat",
            "security",
            "vulnerability",
            "hardening",
            "attack surface",
        ),
        "provider": CANONICAL_EXECUTOR_PROVIDER,
        "model": CANONICAL_EXECUTOR_MODEL,
        "effort": "high",
        "reason": "DeepSeek V4 Pro executes inside the authorized route while GPT-5.6 Sol independently verifies scope and proof quality.",
    },
]

OPENCLAW_RUNTIME_KEYWORDS = (
    "openclaw",
    "openclaw proof",
    "openclaw parity",
    "compare openclaw",
    "test openclaw",
    "debug openclaw",
    "openclaw setup",
    "openclaw auth",
)
OPENCLAW_NEGATION_KEYWORDS = (
    "do not use openclaw",
    "do not relaunch through openclaw",
    "do not launch through openclaw",
    "don't use openclaw",
    "dont use openclaw",
    "avoid openclaw",
    "not openclaw",
    "no openclaw",
    "without openclaw",
 )
HERMES_RUNTIME_KEYWORDS = (
    "browser automation",
    "interactive",
    "oauth",
    "provider setup",
    "broker authentication",
    "terminal",
    "tool exploration",
    "mcp",
    "overnight",
    "hands-free",
    "hands free",
    "continue",
    "resume",
    "watchdog",
    "proof",
    "long",
    "mission",
    "hermes",
)


def _explicit_openclaw_requested(normalized_objective: str) -> bool:
    if any(keyword in normalized_objective for keyword in OPENCLAW_NEGATION_KEYWORDS):
        return False
    return any(keyword in normalized_objective for keyword in OPENCLAW_RUNTIME_KEYWORDS)


def infer_launch_task(objective: str) -> dict[str, Any]:
    normalized = f" {objective or ''} ".lower()
    best: dict[str, Any] | None = None
    best_matches: list[str] = []
    for item in TASK_RECOMMENDATIONS:
        matches = [keyword for keyword in item["keywords"] if keyword in normalized]
        if len(matches) > len(best_matches):
            best = item
            best_matches = matches
    if best is None:
        return {
            "taskType": "general_coding",
            "taskLabel": "General coding",
            "matchedKeywords": [],
            "provider": CANONICAL_EXECUTOR_PROVIDER,
            "model": CANONICAL_EXECUTOR_MODEL,
            "effort": "high",
            "reason": "No specialist task type was detected; use the canonical DeepSeek OpenCode Go executor between independent GPT-5.6 planning and verification.",
        }
    return {
        "taskType": best["taskType"],
        "taskLabel": best["taskLabel"],
        "matchedKeywords": best_matches[:6],
        "provider": best["provider"],
        "model": best["model"],
        "effort": best.get("effort", "high"),
        "reason": best["reason"],
    }


def build_task_route_decision(task: dict[str, Any], runtime: str) -> list[dict[str, str]]:
    executor_provider = str(task.get("provider") or CANONICAL_EXECUTOR_PROVIDER)
    executor_model = str(task.get("model") or CANONICAL_EXECUTOR_MODEL)
    executor_effort = str(task.get("effort") or "high")
    return [
        dict(CONTEXT_READER_LANE),
        {
            "role": "planner",
            "provider": CANONICAL_PLANNER_PROVIDER,
            "model": CANONICAL_PLANNER_MODEL,
            "effort": "high",
            "reason": "GPT-5.6 Sol high decomposes the objective and chooses the route before dispatch.",
        },
        {
            "role": "executor",
            "provider": executor_provider,
            "model": executor_model,
            "effort": executor_effort,
            "reason": str(task.get("reason") or "Executor follows the task-fit route."),
        },
        {
            "role": "verifier",
            "provider": CANONICAL_VERIFIER_PROVIDER,
            "model": CANONICAL_VERIFIER_MODEL,
            "effort": "high",
            "reason": "GPT-5.6 Sol high checks proof, diffs, browser output, and route receipts independently.",
        },
        {
            "role": "supervisor",
            "provider": runtime if runtime in {"hermes", "openclaw"} else "hermes",
            "model": "durable harness",
            "effort": "resume",
            "reason": "The harness owns mission continuity, approvals, watchdogs, and resumability.",
        },
    ]


@checked("launch")
def build_launch_runtime_recommendation(
    *,
    objective: str = "",
    workspace_default_runtime: str = "hermes",
    profile: str = "builder",
) -> dict[str, Any]:
    normalized = f" {objective or ''} ".lower()
    task = infer_launch_task(objective)
    runtime = (workspace_default_runtime or "hermes").strip().lower() or "hermes"
    runtime_reason = "Hermes is the default durable harness for supervised Neyvia missions."
    confidence = 55
    cursor_requested = "cursor" in normalized
    if cursor_requested:
        runtime = "cursor"
        runtime_reason = "Cursor Agent was explicitly requested for this launch."
        confidence = 92
        grok_match = re.search(r"\bgrok[\s_-]*(\d+)(?:[.\s_-]+(\d+))?\b", normalized)
        task = {
            **task,
            "provider": "cursor",
            "model": (
                f"grok-{grok_match.group(1)}-{grok_match.group(2)}"
                if grok_match and grok_match.group(2)
                else f"grok-{grok_match.group(1)}"
                if grok_match
                else "auto"
            ),
            "reason": "The requested Cursor Agent owns execution through its selected model.",
        }
    if not cursor_requested and any(keyword in normalized for keyword in HERMES_RUNTIME_KEYWORDS):
        runtime = "hermes"
        runtime_reason = "Hermes is better for durable supervised missions, provider setup, resume loops, and proof-heavy work."
        confidence = max(confidence, 78)
    explicit_openclaw = _explicit_openclaw_requested(normalized)
    if explicit_openclaw and not cursor_requested:
        runtime = "openclaw"
        runtime_reason = "OpenClaw was explicitly requested for this launch."
        confidence = max(confidence, 82)
    if not objective:
        confidence = 50
    guidance = [
        runtime_reason,
        task["reason"],
        "Leave runtime/model on Auto unless you need a specific provider for the mission.",
    ]
    return {
        "schema": "fluxio.launch_runtime_recommendation.v1",
        "runtime": runtime if runtime in {"hermes", "openclaw", "cursor"} else "hermes",
        "confidence": confidence,
        "profile": profile or "builder",
        "taskType": task["taskType"],
        "taskLabel": task["taskLabel"],
        "matchedKeywords": task["matchedKeywords"],
        "modelProvider": task["provider"],
        "model": task["model"],
        "modelEffort": task.get("effort", "high"),
        "reason": runtime_reason,
        "modelReason": task["reason"],
        "readerLane": dict(CONTEXT_READER_LANE),
        "routeDecisionRows": build_task_route_decision(task, runtime),
        "beginnerSummary": (
            f"Use {runtime.title() if runtime in {'hermes', 'openclaw', 'cursor'} else 'Hermes'} for this launch. "
            "Neyvia reads receipt-bound cache and workspace context first. "
            "Planner and verifier stay on openai-codex / gpt-5.6-sol / high. "
            f"Recommended executor model: {task['provider']} / {task['model']} / {task.get('effort', 'high')}."
        ),
        "guidance": guidance,
    }
