"""Neyvia ecosystem integration hooks (durable, honest).

Neyvia is an ecosystem, not only a workspace. Integrated tools receive a
context pack (shared session, receipts, approvals, memory budgets) so they
perform better inside Neyvia than alone. Own runtime stays strongest.

Silent system-prompt rewrite is intentional ecosystem coaching when enabled —
not a thin clone of Claude Code, and never invents successful executions.
"""

from __future__ import annotations

from typing import Any

ECOSYSTEM_SCHEMA = "neyvia.ecosystem.integration.v1"
AUTO_PROMPT_SCHEMA = "neyvia.auto_prompt.v1"

TASK_PROMPT_PROFILES: dict[str, dict[str, Any]] = {
    "ecosystem_architecture": {
        "label": "Ecosystem architecture",
        "keywords": (
            "architecture", "ecosystem", "system design", "platform", "sdk",
            "marketplace", "orchestration", "runtime", "harness",
        ),
        "contextDepth": "rich",
        "focus": (
            "Preserve the complete product vision, map boundaries and lifecycles, "
            "and make every component strengthen the same ecosystem."
        ),
        "deliverable": "A coherent cross-surface design plus the concrete changes owned by this task.",
        "stopCondition": "Stop only when the named ecosystem relationships are coherent and no ownership boundary is ambiguous.",
        "proofBudget": {"quickChecks": 3, "maximumChecks": 5, "fullSuite": "final-integration-only"},
    },
    "implementation": {
        "label": "Implementation",
        "keywords": (
            "implement", "build", "create", "add", "wire", "integrate", "code",
            "feature", "backend", "frontend",
        ),
        "contextDepth": "bounded",
        "focus": "Implement the requested behavior through the existing architecture with real data flow and no placeholder success.",
        "deliverable": "Working maintainable changes, their affected files, and a small behavioral proof.",
        "stopCondition": "Stop when the requested behavior is complete in the owned scope and the focused proof passes.",
        "proofBudget": {"quickChecks": 3, "maximumChecks": 5, "fullSuite": "final-integration-only"},
    },
    "diagnosis": {
        "label": "Diagnosis and repair",
        "keywords": (
            "diagnose", "debug", "bug", "broken", "failure", "error", "stuck",
            "root cause", "repair", "fix",
        ),
        "contextDepth": "evidence-led",
        "focus": "Find the causal break, distinguish symptoms from causes, and make the smallest durable repair.",
        "deliverable": "Root cause, repair, and a focused regression proof.",
        "stopCondition": "Stop when the causal path is explained and the original failure no longer reproduces in the focused check.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "final-integration-only"},
    },
    "optimization": {
        "label": "Optimization",
        "keywords": (
            "optimize", "optimization", "performance", "speed", "faster",
            "latency", "usage", "efficient", "bottleneck", "memory",
        ),
        "contextDepth": "measured",
        "focus": "Identify the dominant cost first, improve it without weakening correctness, and avoid speculative micro-optimization.",
        "deliverable": "A measurable efficiency change, its trade-offs, and before/after evidence when available.",
        "stopCondition": "Stop when the dominant owned bottleneck is improved or a concrete external limit is proven.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "final-integration-only"},
    },
    "research": {
        "label": "Research and synthesis",
        "keywords": (
            "research", "investigate", "compare", "evaluate", "audit", "study",
            "sources", "evidence", "recommend",
        ),
        "contextDepth": "rich",
        "focus": "Answer the decision, preserve important nuance, separate evidence from inference, and avoid research that does not change the outcome.",
        "deliverable": "A decision-oriented synthesis with traceable evidence and explicit uncertainty.",
        "stopCondition": "Stop when the decision has enough evidence to act, not when every adjacent question is exhausted.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "not-applicable"},
    },
    "study": {
        "label": "Study and learning",
        "keywords": (
            "study", "learn", "student", "flashcard", "quiz", "assignment",
            "course", "lecture", "revision", "explain to me",
        ),
        "contextDepth": "source-led",
        "focus": "Turn the supplied material into understanding and retention while showing which source supports each explanation.",
        "deliverable": "A useful study artifact such as an annotated source, study set, flashcards, quiz, or assignment plan.",
        "stopCondition": "Stop when the requested material is understandable, source-linked, and usable for the learner's next study action.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "not-applicable"},
    },
    "writing": {
        "label": "Writing and publishing",
        "keywords": (
            "write", "writing", "manuscript", "article", "book", "publish",
            "editorial", "redline", "typeset", "bibliography",
        ),
        "contextDepth": "voice-led",
        "focus": "Produce a coherent finished document while preserving the author's intent, voice, sources, and exact requested constraints.",
        "deliverable": "A finished draft plus the requested citations, figures, redlines, or export-ready structure.",
        "stopCondition": "Stop when the document is coherent and ready for its named next stage; external publication or sending still requires approval.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "final-integration-only"},
    },
    "creative": {
        "label": "Creative production",
        "keywords": (
            "creative", "illustration", "design", "audio", "video", "3d",
            "game", "storyboard", "visual identity",
        ),
        "contextDepth": "intent-led",
        "focus": "Preserve the creative intent across iterations, keep manifests and references attached, and prepare a presentation or export without flattening the concept.",
        "deliverable": "A coherent creative artifact set with its iteration lineage and requested presentation.",
        "stopCondition": "Stop when the requested artifact exists with truthful lineage or a concrete adapter limit is reported.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "final-integration-only"},
    },
    "communication": {
        "label": "Communication",
        "keywords": (
            "email", "mail", "message", "campaign", "reply", "newsletter",
            "social post", "announce", "audience",
        ),
        "contextDepth": "audience-led",
        "focus": "Prepare the message for its audience and account boundary; drafts may be automated, but sending, deleting, and unsubscribing remain per-action approvals.",
        "deliverable": "A channel-appropriate draft and any selected assets or Share Capsule.",
        "stopCondition": "Stop at a reviewed draft or prepared capsule unless the user explicitly approves the external action.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 3, "fullSuite": "not-applicable"},
    },
    "experimentation": {
        "label": "Maker and experimentation",
        "keywords": (
            "experiment", "maker", "device", "flipper", "firmware", "serial",
            "bluetooth", "prototype", "tinker", "hardware",
        ),
        "contextDepth": "boundary-led",
        "focus": "State the hypothesis, baseline, lifetime, target and authorization; label every operation Observe, Simulate, or Act and retain failures.",
        "deliverable": "A bounded experiment with a measurement journal, evidence, and an explicit verdict or promotion plan.",
        "stopCondition": "Stop when the experiment has a retained verdict; Act operations always require a named target and per-action approval.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "final-integration-only"},
    },
    "ui_ux": {
        "label": "UI and user experience",
        "keywords": (
            "ui", "ux", "interface", "screen", "interaction", "workflow",
            "responsive", "accessibility", "user experience", "visual design",
        ),
        "contextDepth": "journey-led",
        "focus": "Design from the operator's journey, make state and consequences legible, and keep advanced power available without visual noise.",
        "deliverable": "A coherent interaction in the existing design language with truthful empty, loading, error, and lifecycle states.",
        "stopCondition": "Stop when the complete named journey works and each consequential state is understandable.",
        "proofBudget": {"quickChecks": 3, "maximumChecks": 5, "fullSuite": "final-integration-only"},
    },
    "image_generation": {
        "label": "Image generation",
        "keywords": (
            "image", "illustration", "photo", "render", "poster", "logo",
            "visual", "generate picture", "edit image",
        ),
        "contextDepth": "visual-spec",
        "focus": "Translate intent into subject, composition, style, light, palette, camera, material, text, and preservation constraints without changing the requested concept.",
        "deliverable": "A provider-ready visual specification that preserves exact requested text and reference constraints.",
        "stopCondition": "Stop after the requested image operation returns a real artifact or a truthful provider error.",
        "proofBudget": {"quickChecks": 1, "maximumChecks": 2, "fullSuite": "not-applicable"},
    },
    "security": {
        "label": "Security and red-team",
        "keywords": (
            "security", "red team", "threat", "vulnerability", "exploit",
            "attack surface", "hardening", "abuse",
        ),
        "contextDepth": "boundary-led",
        "focus": "Work inside the authorized boundary, model realistic abuse, preserve evidence, and prioritize durable mitigation.",
        "deliverable": "Reproducible findings, impact, and proportionate fixes or detections.",
        "stopCondition": "Stop when the scoped risk is demonstrated or ruled out and the mitigation path is actionable.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "final-integration-only"},
    },
    "general": {
        "label": "General task",
        "keywords": (),
        "contextDepth": "bounded",
        "focus": "Advance the user's stated outcome directly, preserve constraints, and avoid unrelated work.",
        "deliverable": "The requested outcome with concise evidence.",
        "stopCondition": "Stop when the stated outcome is delivered or a concrete blocker is proven.",
        "proofBudget": {"quickChecks": 2, "maximumChecks": 4, "fullSuite": "final-integration-only"},
    },
}

TASK_PROMPT_PRIORITY = (
    "image_generation",
    "security",
    "ecosystem_architecture",
    "diagnosis",
    "optimization",
    "ui_ux",
    "experimentation",
    "study",
    "communication",
    "writing",
    "creative",
    "research",
    "implementation",
)

SESSION_TOOL_BENEFITS: dict[str, tuple[str, ...]] = {
    "pdf": ("shared-artifacts", "receipts", "memory-budget", "app-share"),
    "research": ("shared-context", "receipts", "approvals", "memory-budget"),
    "translate": ("shared-artifacts", "memory-budget", "app-share"),
    "grammar": ("shared-artifacts", "memory-budget", "receipts"),
    "chart": ("shared-artifacts", "receipts", "app-share"),
    "web-capture": ("shared-artifacts", "receipts", "approvals"),
    "tools": ("capability-snapshot", "approvals", "receipts", "shared-context"),
    "sources": ("receipts", "shared-context", "memory-budget"),
    "managed-cli": (
        "shared-context",
        "receipts",
        "approvals",
        "capability-snapshot",
        "orchestration-linkage",
        "memory-budget",
        "resilience",
    ),
    "terminal": ("receipts", "approvals", "shared-context"),
    "data": ("shared-artifacts", "memory-budget", "app-share"),
}

BENEFIT_COPY: dict[str, str] = {
    "shared-context": "Shared session + constellation context (not a cold start).",
    "receipts": "Proof strip / tool receipts when the backend returns them — never invented.",
    "approvals": "Plan → approve gates stay owned by Neyvia.",
    "shared-artifacts": "Honest hooks to session artifacts / library picks when present.",
    "memory-budget": "Memory and context budgets coordinated by the shell.",
    "resilience": "Queued turns survive until a harness receipt arrives.",
    "app-share": "App-share / artifact handoff when the share surface is connected.",
    "capability-snapshot": "Capability OS snapshot for truthful agentReady claims.",
    "orchestration-linkage": "Focus Grid / constellation role linkage.",
}


def _runtime_label(runtime: str) -> str:
    key = str(runtime or "").strip().lower()
    if key == "grok-build":
        return "Grok Build"
    if key == "claude-code":
        return "Claude Code"
    return key or "integrated lane"


def infer_task_prompt_profile(
    subject: str,
    *,
    requested_profile: str | None = None,
) -> dict[str, Any]:
    """Select a transparent, deterministic task contract without an extra model call."""

    requested = str(requested_profile or "").strip().lower().replace("-", "_")
    if requested in TASK_PROMPT_PROFILES:
        profile_id = requested
        matched: list[str] = []
        source = "explicit"
    else:
        normalized = f" {str(subject or '').lower()} "
        candidates: list[tuple[int, int, str, list[str]]] = []
        for priority, candidate_id in enumerate(TASK_PROMPT_PRIORITY):
            keywords = TASK_PROMPT_PROFILES[candidate_id]["keywords"]
            matches = [keyword for keyword in keywords if keyword in normalized]
            if matches:
                candidates.append((len(matches), -priority, candidate_id, matches))
        if candidates:
            _, _, profile_id, matched = max(candidates)
            source = "inferred"
        else:
            profile_id, matched, source = "general", [], "default"
    profile = TASK_PROMPT_PROFILES[profile_id]
    result = {
        "schema": AUTO_PROMPT_SCHEMA,
        "profileId": profile_id,
        "label": profile["label"],
        "selection": source,
        "matchedSignals": matched[:8],
        "contextDepth": profile["contextDepth"],
        "focus": profile["focus"],
        "deliverable": profile["deliverable"],
        "stopCondition": profile["stopCondition"],
        "proofBudget": dict(profile["proofBudget"]),
    }
    from .proofs_d_neyvia import check_profile
    check_profile(subject, requested_profile, result)
    return result


def _context_lines(task_context: dict[str, Any] | None) -> list[str]:
    context = task_context if isinstance(task_context, dict) else {}
    labels = (
        ("scope", "Owned scope"),
        ("ownership", "Ownership"),
        ("doNotTouch", "Do not modify"),
        ("success", "Success"),
        ("constraints", "Constraints"),
        ("currentState", "Current state"),
    )
    lines: list[str] = []
    for key, label in labels:
        value = context.get(key)
        if isinstance(value, (list, tuple)):
            value = "; ".join(str(item).strip() for item in value if str(item).strip())
        value = str(value or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    return lines


def build_adaptive_task_prompt(
    prompt: str,
    *,
    pack: dict[str, Any] | None = None,
    requested_profile: str | None = None,
    task_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile an execution brief while retaining the user's request verbatim."""

    original = str(prompt or "")
    context = pack if isinstance(pack, dict) else build_ecosystem_context_pack()
    subject = "\n".join(
        item
        for item in (
            original,
            str((task_context or {}).get("currentState") or ""),
            str((task_context or {}).get("scope") or ""),
        )
        if item
    )
    profile = infer_task_prompt_profile(subject, requested_profile=requested_profile)
    proof = profile["proofBudget"]
    sections = [
        f"[Neyvia adaptive task contract — {profile['label']}]",
        f"Task profile: {profile['profileId']} ({profile['selection']}).",
        f"Context policy: {profile['contextDepth']}.",
        f"Focus: {profile['focus']}",
        f"Required return: {profile['deliverable']}",
        f"Stop condition: {profile['stopCondition']}",
        (
            "Proof budget: "
            f"{proof['quickChecks']} focused checks by default, never more than "
            f"{proof['maximumChecks']} for this milestone; full suite: {proof['fullSuite']}."
        ),
        (
            "Layer contract: orchestration owns task division and sequence; the harness "
            "owns permissions, budgets, receipts, and stop enforcement; the runtime owns "
            "execution; this auto-prompt only prepares the task contract."
        ),
    ]
    if profile["contextDepth"] == "rich":
        sections.append(
            "Context preservation: retain the complete supplied vision and important "
            "relationships; do not compress away product intent merely to shorten the brief."
        )
    sections.extend(_context_lines(task_context))
    conversation_id = context.get("conversationId")
    if conversation_id:
        sections.append(f"Conversation linkage: {conversation_id}")
    sections.extend(
        [
            "",
            "[Original user request — preserve as authoritative]",
            original,
        ]
    )
    result = {
        "schema": AUTO_PROMPT_SCHEMA,
        "profile": profile,
        "originalPrompt": original,
        "prompt": "\n".join(sections).strip(),
    }
    from .proofs_d_neyvia import check_prompt
    check_prompt(original, task_context, result)
    return result


def build_image_generation_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a visual specification, not a coding-agent prompt."""

    prompt = payload.get("prompt") if isinstance(payload.get("prompt"), dict) else {}
    original = str(prompt.get("text") or payload.get("instruction") or "").strip()
    profile = infer_task_prompt_profile(original, requested_profile="image_generation")
    fields = (
        ("Subject and intent", original),
        ("Operation", payload.get("operation")),
        ("Composition", payload.get("compositionIntent")),
        ("Style and art direction", prompt.get("style")),
        ("Lighting and atmosphere", prompt.get("lighting")),
        ("Palette", prompt.get("palette")),
        ("Camera and framing", prompt.get("camera")),
        ("Materials and texture", prompt.get("materials")),
        ("Exact visible text", prompt.get("exactText") or prompt.get("textContent")),
        ("Preservation constraints", prompt.get("preserve") or payload.get("preserve")),
        ("Avoid", prompt.get("negative")),
    )
    lines = [
        "[Neyvia image-generation profile]",
        "Preserve the requested concept and any exact visible text. Do not add unrequested copy, logos, or subjects.",
    ]
    for label, value in fields:
        if isinstance(value, (list, tuple)):
            value = "; ".join(str(item).strip() for item in value if str(item).strip())
        value = str(value or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    canvas = payload.get("canvas") if isinstance(payload.get("canvas"), dict) else {}
    if canvas:
        lines.append(
            "Canvas: "
            f"{canvas.get('width') or 'auto'}×{canvas.get('height') or 'auto'}"
        )
    result = {
        "schema": AUTO_PROMPT_SCHEMA,
        "profile": profile,
        "originalPrompt": original,
        "prompt": "\n".join(lines),
    }
    from .proofs_d_neyvia import check_image
    check_image(fields, result)
    return result


def build_ecosystem_context_pack(
    *,
    runtime: str = "claude-code",
    conversation_id: str | None = None,
    capability_snapshot: dict[str, Any] | None = None,
    silent_rewrite: bool = True,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_id = str(runtime or "claude-code").strip().lower()
    benefits = [
        {"id": benefit_id, "copy": BENEFIT_COPY.get(benefit_id, benefit_id)}
        for benefit_id in SESSION_TOOL_BENEFITS.get("managed-cli", ())
    ]
    snapshot_summary: dict[str, Any] | None = None
    if isinstance(capability_snapshot, dict):
        summary = capability_snapshot.get("summary")
        summary = summary if isinstance(summary, dict) else {}
        snapshot_summary = {
            "packs": capability_snapshot.get("packs", summary.get("packs")),
            "availableCapabilities": capability_snapshot.get(
                "availableCapabilities",
                summary.get("availableCapabilities"),
            ),
            "agentReadyTools": capability_snapshot.get("agentReadyTools"),
        }
    return {
        "schema": ECOSYSTEM_SCHEMA,
        "product": "Neyvia",
        "productSpell": "N-E-Y-V-I-A",
        "runtime": runtime_id,
        "runtimeLabel": _runtime_label(runtime_id),
        "conversationId": conversation_id,
        "silentRewrite": bool(silent_rewrite),
        "ranking": {
            "ownRuntime": "strongest",
            "integratedLane": "stronger_than_standalone",
            "standalone": "baseline",
        },
        "benefits": benefits,
        "capabilitySnapshot": snapshot_summary,
        "extras": extras if isinstance(extras, dict) else None,
        "honesty": {
            "inventSuccess": False,
            "agentReadyRequiresBackend": True,
            "queuedUntilReceipt": True,
        },
    }


def build_silent_ecosystem_rewrite_prompt(pack: dict[str, Any] | None = None) -> str:
    context = pack if isinstance(pack, dict) else build_ecosystem_context_pack()
    benefit_lines = "\n".join(
        f"- {item.get('copy') or item.get('id')}"
        for item in (context.get("benefits") or [])
        if isinstance(item, dict)
    ) or "- Shared context and proof hooks when connected."
    lines = [
        "[Neyvia ecosystem coaching — silent rewrite enabled]",
        (
            f"You are running as {context.get('runtimeLabel') or 'an integrated lane'} "
            "inside N-E-Y-V-I-A (Neyvia), not alone."
        ),
        (
            "Neyvia chrome and mission ownership stay Neyvia; this rewrite only adds "
            "ecosystem advantages so this lane outperforms a standalone CLI."
        ),
        (
            "Use shared session/constellation context, respect plan→approve gates, "
            "emit/await real receipts, and never invent successful executions."
        ),
        "Capability claims must match backend agentReady / harness receipts.",
        "Advantages in this session:",
        benefit_lines,
    ]
    conversation_id = context.get("conversationId")
    if conversation_id:
        lines.append(f"Conversation linkage: {conversation_id}")
    snapshot = context.get("capabilitySnapshot")
    if isinstance(snapshot, dict) and snapshot.get("agentReadyTools") is not None:
        lines.append(f"Capability snapshot agentReadyTools: {snapshot['agentReadyTools']}")
    return "\n".join(lines)


def apply_silent_ecosystem_rewrite(
    prompt: str,
    *,
    enabled: bool = True,
    pack: dict[str, Any] | None = None,
    requested_profile: str | None = None,
    task_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return rewritten prompt metadata. Never claims execute success."""
    original = str(prompt or "")
    if not enabled:
        result = {
            "ok": True,
            "silentRewrite": False,
            "prompt": original,
            "rewritten": False,
            "status": "rewrite_disabled",
        }
        from .proofs_d_neyvia import check_rewrite
        check_rewrite(original, enabled, result)
        return result
    coaching = build_silent_ecosystem_rewrite_prompt(pack)
    adaptive = build_adaptive_task_prompt(
        original,
        pack=pack,
        requested_profile=requested_profile,
        task_context=task_context,
    )
    merged = f"{coaching}\n\n---\n\n{adaptive['prompt']}"
    result = {
        "ok": True,
        "silentRewrite": True,
        "prompt": merged,
        "rewritten": True,
        "status": "ecosystem_coaching_applied",
        "pack": pack if isinstance(pack, dict) else build_ecosystem_context_pack(),
        "autoPrompt": adaptive,
    }
    from .proofs_d_neyvia import check_rewrite
    check_rewrite(original, enabled, result)
    return result
