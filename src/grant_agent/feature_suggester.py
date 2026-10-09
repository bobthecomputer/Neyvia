from __future__ import annotations

from .proofs_b_engine import checked as _proofs_b_checked

import re


FEATURE_LIBRARY = [
    {
        "id": "adaptive_routing",
        "keywords": ["model", "router", "cost", "latency", "quality"],
        "title": "Adaptive Model Routing",
        "why": "Route each step to the best model profile for speed, quality, and cost.",
        "mvp": "Add per-step policy that chooses a model by task type and budget ceiling.",
    },
    {
        "id": "memory_long_horizon",
        "keywords": ["memory", "long", "context", "resume", "continuity"],
        "title": "Long-Horizon Memory",
        "why": "Keep decisions and risks across runs so the agent stays aligned over time.",
        "mvp": "Store compact memory items and retrieve top relevant snippets before each run.",
    },
    {
        "id": "verification_matrix",
        "keywords": ["test", "verify", "ci", "quality", "regression"],
        "title": "Verification Matrix",
        "why": "Map change types to checks so verification is automatic and proportional.",
        "mvp": "Detect changed file types and select lint/test/build commands by matrix rules.",
    },
    {
        "id": "preview_snapshots",
        "keywords": ["ui", "preview", "snapshot", "compare", "frontend"],
        "title": "Preview Snapshot Diff",
        "why": "Reduce UI guesswork by comparing before/after snapshots automatically.",
        "mvp": "Capture baseline and post-change screenshots, then compute visual diff score.",
    },
    {
        "id": "budget_guardrails",
        "keywords": ["budget", "spend", "token", "limit", "cost"],
        "title": "Budget Guardrails",
        "why": "Prevent runaway autonomous loops and surprise costs.",
        "mvp": "Expose token, handoff, and runtime limits with stop reasons in artifacts.",
    },
    {
        "id": "human_checkpoints",
        "keywords": ["approval", "human", "checkpoint", "control", "safety"],
        "title": "Human Checkpoints",
        "why": "Keep user vision in control for risky or high-impact steps.",
        "mvp": "Pause for approval when command risk >= medium or when touching sensitive files.",
    },
    {
        "id": "benchmark_dashboard",
        "keywords": ["benchmark", "metric", "dashboard", "evaluate", "performance"],
        "title": "Benchmark Dashboard",
        "why": "Track objective progress and prove improvements publicly.",
        "mvp": "Aggregate run metrics into a single report with trend deltas per week.",
    },
]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@_proofs_b_checked("proofs-b.engine.suggestions")
def suggest_features_from_text(text: str, top_k: int = 6) -> list[dict]:
    tokens = _tokens(text)

    def score(feature: dict) -> int:
        return len(tokens & set(feature["keywords"]))

    ranked = sorted(FEATURE_LIBRARY, key=score, reverse=True)
    picked = [item for item in ranked if score(item) > 0]
    if not picked:
        picked = ranked
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "why": item["why"],
            "mvp": item["mvp"],
            "score": score(item),
        }
        for item in picked[:top_k]
    ]
